"""Deterministic 8x8 two-reservoir SUMO network and hysteresis demand generator.

Emits SUMO plain-XML inputs (nodes, edges, traffic lights, demand flows, and a
.sumocfg bundle) and builds `grid_2res.net.xml` through `netconvert`. The
network is split into a west and an east reservoir at the vertical line between
grid columns 3 and 4; the reservoir-boundary edges plus the outer ring are
labelled arterial, all remaining edges are local streets. The 5400 s demand
profile follows the pre-registered hysteresis shape (ramp-up, overload plateau,
recovery drop) so closed-loop episodes exercise both MFD branches.

All counts are deterministic: no PRNG is consumed, flow sizes are exact
rounded rates per fixed 60 s interval.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

GRID_SIZE = 8
BLOCK_M = 150.0
ARTERIAL_SPEED_MS = 13.89
LOCAL_SPEED_MS = 8.33
EPISODE_LENGTH_S = 5400
DEMAND_INTERVAL_S = 60
RESERVOIR_BOUNDARY_COL = 4

# Pre-registered hysteresis demand shape (veh/s at the network entries). The
# overload plateau deliberately exceeds the reference MFD capacity (~1.5 veh/s)
# so closed-loop episodes traverse the congested branch of the diagram.
RAMP_UP_END_S = 1800
PLATEAU_END_S = 3600
Q_RAMP_START = 0.30
Q_OVERLOAD = 2.00
Q_RECOVERY = 0.50


@dataclass(frozen=True)
class GridSpec:
    grid_size: int = GRID_SIZE
    block_m: float = BLOCK_M
    arterial_speed_ms: float = ARTERIAL_SPEED_MS
    local_speed_ms: float = LOCAL_SPEED_MS


def hysteresis_inflow_veh_s(t_s: float) -> float:
    """Deterministic demand envelope: linear ramp-up, overload plateau,
    recovery drop (loading -> congestion -> unloading)."""
    if t_s < 0.0 or t_s >= EPISODE_LENGTH_S:
        return 0.0
    if t_s < RAMP_UP_END_S:
        frac = t_s / RAMP_UP_END_S
        return Q_RAMP_START + (Q_OVERLOAD - Q_RAMP_START) * frac
    if t_s < PLATEAU_END_S:
        return Q_OVERLOAD
    frac = (t_s - PLATEAU_END_S) / max(1.0, EPISODE_LENGTH_S - PLATEAU_END_S)
    return Q_OVERLOAD + (Q_RECOVERY - Q_OVERLOAD) * frac


def is_boundary_edge(i_from: int, j_from: int, i_to: int, j_to: int) -> bool:
    """True when the directed edge crosses the west/east reservoir split."""
    west = min(i_from, i_to)
    east = max(i_from, i_to)
    return west == RESERVOIR_BOUNDARY_COL - 1 and east == RESERVOIR_BOUNDARY_COL


def is_outer_ring_edge(i_from: int, j_from: int, i_to: int, j_to: int) -> bool:
    ring = {0, GRID_SIZE - 1}
    if j_from == j_to and j_from in ring:
        return True
    return i_from == i_to and i_from in ring


def link_class(i_from: int, j_from: int, i_to: int, j_to: int) -> str:
    if is_boundary_edge(i_from, j_from, i_to, j_to) or is_outer_ring_edge(
        i_from, j_from, i_to, j_to
    ):
        return "arterial"
    return "local"


def edge_id(i_from: int, j_from: int, i_to: int, j_to: int) -> str:
    return f"e{i_from}_{j_from}-{i_to}_{j_to}"


def node_id(i: int, j: int) -> str:
    return f"n{i}_{j}"


def _adjacent(i: int, j: int, size: int) -> list[tuple[int, int]]:
    for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        ni, nj = i + di, j + dj
        if 0 <= ni < size and 0 <= nj < size:
            yield ni, nj


def classify_network(spec: GridSpec = GridSpec()) -> dict[str, list[str]]:
    """Return {'arterial': [...], 'local': [...]} edge-id classifications and
    per-class total lane length in km (single lane per edge)."""
    classes: dict[str, list[str]] = {"arterial": [], "local": []}
    for j in range(spec.grid_size):
        for i in range(spec.grid_size):
            for ni, nj in _adjacent(i, j, spec.grid_size):
                classes[link_class(i, j, ni, nj)].append(edge_id(i, j, ni, nj))
    return classes


def class_lengths_km(spec: GridSpec = GridSpec()) -> dict[str, float]:
    classes = classify_network(spec)
    return {
        name: len(edges) * spec.block_m / 1000.0 for name, edges in classes.items()
    }


def _write_plain_xml(out_dir: Path, spec: GridSpec) -> dict[str, Path]:
    nod_path = out_dir / "grid_2res.nod.xml"
    edg_path = out_dir / "grid_2res.edg.xml"
    tll_path = out_dir / "grid_2res.tll.xml"

    nodes = ET.Element("nodes")
    for j in range(spec.grid_size):
        for i in range(spec.grid_size):
            # Traffic lights sit on the internal reservoir boundary column so
            # perimeter gating can throttle west->east flow.
            junction_type = (
                "traffic_light"
                if i == RESERVOIR_BOUNDARY_COL and 0 < j < spec.grid_size - 1
                else "priority"
            )
            ET.SubElement(
                nodes,
                "node",
                id=node_id(i, j),
                x=f"{i * spec.block_m:.2f}",
                y=f"{j * spec.block_m:.2f}",
                type=junction_type,
            )

    edges = ET.Element("edges")
    for j in range(spec.grid_size):
        for i in range(spec.grid_size):
            for ni, nj in _adjacent(i, j, spec.grid_size):
                klass = link_class(i, j, ni, nj)
                ET.SubElement(
                    edges,
                    "edge",
                    id=edge_id(i, j, ni, nj),
                    **{
                        "from": node_id(i, j),
                        "to": node_id(ni, nj),
                        "numLanes": "1",
                        "speed": f"{spec.arterial_speed_ms if klass == 'arterial' else spec.local_speed_ms:.2f}",
                        "priority": "3" if klass == "arterial" else "1",
                    },
                )

    # Explicit static two-phase programs for every boundary junction: phase 0
    # releases the east-west (reservoir-crossing) movement, phase 1 the
    # north-south movement. The runner actuates phase 0 durations.
    tlls = ET.Element("tls")
    tls_ids = [
        node_id(RESERVOIR_BOUNDARY_COL, j)
        for j in range(1, spec.grid_size - 1)
    ]
    for tls_id in tls_ids:
        tl_logic = ET.SubElement(tlls, "tlLogic", id=tls_id, type="static", programID="perimeter", offset="0")
        ET.SubElement(tl_logic, "phase", duration="30", state="GGGrrrGGGrrr")
        ET.SubElement(tl_logic, "phase", duration="4", state="yyyrrryyyrrr")
        ET.SubElement(tl_logic, "phase", duration="30", state="rrrGrrrrrGrr")
        ET.SubElement(tl_logic, "phase", duration="4", state="rrryrrrrryrr")

    for element, path in ((nodes, nod_path), (edges, edg_path), (tlls, tll_path)):
        _indent(element)
        ET.ElementTree(element).write(path, encoding="utf-8", xml_declaration=True)

    return {"nodes": nod_path, "edges": edg_path, "tls": tll_path}


def _indent(elem: ET.Element, level: int = 0) -> None:
    pad = "\n" + level * "  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = pad + "  "
        for child in elem:
            _indent(child, level + 1)
            if not child.tail or not child.tail.strip():
                child.tail = pad + "  "
        if not elem[-1].tail or not elem[-1].tail.strip():
            elem[-1].tail = pad
    elif level and (not elem.tail or not elem.tail.strip()):
        elem.tail = pad


def _locate_netconvert() -> str:
    env_home = os.environ.get("SUMO_HOME")
    candidates: list[str] = []
    if env_home:
        candidates.append(str(Path(env_home) / "bin" / "netconvert"))
    found = shutil.which("netconvert")
    if found:
        candidates.insert(0, found)
    try:
        from sumolib import checkBinary  # type: ignore

        candidates.append(checkBinary("netconvert"))
    except Exception:
        pass
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return "netconvert"


def build_net(out_dir: Path, spec: GridSpec = GridSpec()) -> Path:
    """Build grid_2res.net.xml from the plain-XML inputs via netconvert."""
    inputs = _write_plain_xml(out_dir, spec)
    net_path = out_dir / "grid_2res.net.xml"
    command = [
        _locate_netconvert(),
        "--node-files", str(inputs["nodes"]),
        "--edge-files", str(inputs["edges"]),
        "--tllogic-files", str(inputs["tls"]),
        "--output-file", str(net_path),
        "--no-turnarounds", "true",
        "--offset.disable-normalization", "true",
    ]
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0 or not net_path.exists():
        raise RuntimeError(
            "netconvert failed while building the two-reservoir network: "
            f"{completed.stderr.strip()}"
        )
    return net_path


def _route_edges(
    start: tuple[int, int], end: tuple[int, int], spec: GridSpec
) -> list[str]:
    """Deterministic L-shaped route: horizontal first, then vertical."""
    (i0, j0), (i1, j1) = start, end
    edges: list[str] = []
    step_i = 1 if i1 >= i0 else -1
    for i in range(i0, i1, step_i):
        edges.append(edge_id(i, j0, i + step_i, j0))
    step_j = 1 if j1 >= j0 else -1
    for j in range(j0, j1, step_j):
        edges.append(edge_id(i1, j, i1, j + step_j))
    return edges


def generate_demand(out_dir: Path, spec: GridSpec = GridSpec()) -> Path:
    """Write demand_hysteresis.rou.xml: cross-reservoir (west<->east) and
    intra-reservoir trips drawn from the hysteresis envelope, in exact
    per-interval vehicle counts."""
    size = spec.grid_size
    boundary = RESERVOIR_BOUNDARY_COL
    west_entries = [(0, j) for j in range(size)]
    east_entries = [(size - 1, j) for j in range(size)]

    cross_routes: list[tuple[str, str, list[str]]] = []
    for j in range(size):
        cross_routes.append(
            (f"we_{j}", "west_to_east", _route_edges((0, j), (size - 1, j), spec))
        )
        cross_routes.append(
            (f"ew_{j}", "east_to_west", _route_edges((size - 1, j), (0, j), spec))
        )
    intra_routes: list[tuple[str, str, list[str]]] = []
    for reservoir, entries in (("west", west_entries[:boundary]), ("east", east_entries[boundary:])):
        for a in range(len(entries)):
            for b in range(len(entries)):
                if a != b and (a + b) % 2 == 0:
                    intra_routes.append(
                        (
                            f"intra_{reservoir}_{a}_{b}",
                            f"intra_{reservoir}",
                            _route_edges(entries[a], entries[b], spec),
                        )
                    )

    routes = ET.Element("routes")
    for route_id, _tag, edges in cross_routes + intra_routes:
        ET.SubElement(routes, "route", id=route_id, edges=" ".join(edges))

    interval_index = 0
    for begin in range(0, EPISODE_LENGTH_S, DEMAND_INTERVAL_S):
        end = begin + DEMAND_INTERVAL_S
        rate = hysteresis_inflow_veh_s(begin + 0.5 * DEMAND_INTERVAL_S)
        # Half of the envelope crosses the boundary in each direction; the
        # remainder is split evenly over the pre-built intra-reservoir routes.
        cross_total = int(round(rate * DEMAND_INTERVAL_S * 0.5))
        intra_total = int(round(rate * DEMAND_INTERVAL_S * 0.25))
        for direction in (0, 1):
            subset = [r for r in cross_routes if (r[1] == "west_to_east") == (direction == 0)]
            for k, (route_id, _tag, _edges) in enumerate(subset):
                number = cross_total // len(subset) + (1 if k < cross_total % len(subset) else 0)
                if number <= 0:
                    continue
                ET.SubElement(
                    routes,
                    "flow",
                    id=f"flow_{interval_index}_{route_id}",
                    type="passenger",
                    route=route_id,
                    begin=str(begin),
                    end=str(end),
                    number=str(number),
                    departSpeed="max",
                    departLane="best",
                )
        for k, (route_id, _tag, _edges) in enumerate(intra_routes):
            number = intra_total // len(intra_routes) + (1 if k < intra_total % len(intra_routes) else 0)
            if number <= 0:
                continue
            ET.SubElement(
                routes,
                "flow",
                id=f"flow_{interval_index}_{route_id}",
                type="passenger",
                route=route_id,
                begin=str(begin),
                end=str(end),
                number=str(number),
                departSpeed="max",
                departLane="best",
            )
        interval_index += 1

    _indent(routes)
    rou_path = out_dir / "demand_hysteresis.rou.xml"
    ET.ElementTree(routes).write(rou_path, encoding="utf-8", xml_declaration=True)
    return rou_path


def write_sumocfg(out_dir: Path, net_path: Path, rou_path: Path) -> Path:
    cfg = ET.Element("configuration")
    inp = ET.SubElement(cfg, "input")
    ET.SubElement(inp, "net-file", value=net_path.name)
    ET.SubElement(inp, "route-files", value=rou_path.name)
    time_cfg = ET.SubElement(cfg, "time")
    ET.SubElement(time_cfg, "begin", value="0")
    ET.SubElement(time_cfg, "end", value=str(EPISODE_LENGTH_S))
    ET.SubElement(time_cfg, "step-length", value="1")
    processing = ET.SubElement(cfg, "processing")
    ET.SubElement(processing, "time-to-teleport", value="-1")
    ET.SubElement(processing, "default.speeddev", value="0")
    _indent(cfg)
    cfg_path = out_dir / "grid_2res.sumocfg"
    ET.ElementTree(cfg).write(cfg_path, encoding="utf-8", xml_declaration=True)
    return cfg_path


def generate_network(out_dir: Path = Path("results/network")) -> dict:
    """Full deterministic generation pass. Returns the artifact paths plus the
    arterial/local lane-length split consumed by the estimators."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    spec = GridSpec()
    net_path = build_net(out_dir, spec)
    rou_path = generate_demand(out_dir, spec)
    cfg_path = write_sumocfg(out_dir, net_path, rou_path)
    return {
        "net": net_path,
        "demand": rou_path,
        "sumocfg": cfg_path,
        "class_lengths_km": class_lengths_km(spec),
        "episode_length_s": EPISODE_LENGTH_S,
    }


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("results/network")
    summary = generate_network(target)
    print(f"network written to {summary['net']}")
    print(f"demand written to {summary['demand']}")
    print(f"class lengths (km): {summary['class_lengths_km']}")
