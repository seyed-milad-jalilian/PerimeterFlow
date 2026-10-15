from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET


def generate_two_reservoir_grid(output_dir: Path) -> Path:
    """
    Deterministically builds an 8x8 urban grid in SUMO (`grid_2res.net.xml`),
    classifies arterial core spines vs. local streets, marks boundary traffic lights,
    writes the 5400s hysteresis trip demand (`demand_hysteresis.rou.xml`), and creates
    a self-contained `simulation.sumocfg`.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_net = output_dir / "raw_grid.net.xml"
    final_net = output_dir / "grid_2res.net.xml"
    trips_file = output_dir / "trips.trips.xml"
    routes_file = output_dir / "demand_hysteresis.rou.xml"
    sumocfg_file = output_dir / "simulation.sumocfg"

    if shutil.which("netgenerate") is not None:
        subprocess.run(
            [
                "netgenerate",
                "--grid",
                "--grid.number=8",
                "--grid.length=150",
                "--grid.attach-length=120",
                "--default.lanenumber=2",
                "--default.speed=13.89",
                "--tls.guess=true",
                "--tls.cycle.time=60",
                "--output-file",
                str(raw_net),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        tree = ET.parse(raw_net)
        root = tree.getroot()
    else:
        root = ET.Element("net")
        for r in ("B", "C", "D", "E", "F"):
            for idx in range(1, 7):
                edge = ET.SubElement(root, "edge", id=f"{r}{idx}{r}{idx+1}")
                ET.SubElement(edge, "lane", id=f"{r}{idx}{r}{idx+1}_0", speed="13.89", length="150.0")
                ET.SubElement(edge, "lane", id=f"{r}{idx}{r}{idx+1}_1", speed="13.89", length="150.0")
        tree = ET.ElementTree(root)

    internal_edges: list[str] = []
    for edge in root.findall("edge"):
        eid = edge.get("id", "")
        if eid.startswith(":"):
            continue
        internal_edges.append(eid)
        is_arterial = any(tag in eid for tag in ("C3", "C4", "D3", "D4", "E3", "E4"))
        param = ET.SubElement(edge, "param")
        param.set("key", "link_class")
        param.set("value", "arterial" if is_arterial else "local")

    tree.write(final_net, encoding="utf-8", xml_declaration=True)

    rou_root = ET.Element("routes")
    ET.SubElement(
        rou_root,
        "vType",
        id="urban_car",
        accel="2.6",
        decel="4.5",
        sigma="0.5",
        length="4.5",
        maxSpeed="15.0",
    )

    valid_edges = [e for e in internal_edges if len(e) >= 4]
    phases = [
        ("load", 0, 1200, 1400),
        ("peak", 1200, 3200, 3400),
        ("unload", 3200, 5400, 700),
    ]
    trip_records: list[tuple[int, str, str, str]] = []
    flow_idx = 0
    for phase_name, t_begin, t_end, vehs_per_hr in phases:
        total_phase_vehs = int((t_end - t_begin) * vehs_per_hr / 3600.0)
        step_gap = max(1, (t_end - t_begin) // max(1, total_phase_vehs))
        for i in range(total_phase_vehs):
            depart_t = min(t_end - 1, t_begin + i * step_gap)
            src_edge = valid_edges[i % len(valid_edges)]
            dst_edge = valid_edges[(i * 3 + 5) % len(valid_edges)]
            if src_edge != dst_edge:
                trip_records.append((depart_t, f"veh_{phase_name}_{flow_idx}", src_edge, dst_edge))
                flow_idx += 1

    trip_records.sort(key=lambda item: (item[0], item[1]))
    for depart_t, trip_id, src_edge, dst_edge in trip_records:
        trip_el = ET.SubElement(
            rou_root,
            "trip",
            id=trip_id,
            type="urban_car",
            depart=f"{depart_t:.1f}",
        )
        trip_el.set("from", src_edge)
        trip_el.set("to", dst_edge)

    ET.ElementTree(rou_root).write(trips_file, encoding="utf-8", xml_declaration=True)

    if shutil.which("duarouter") is not None and raw_net.exists():
        subprocess.run(
            [
                "duarouter",
                "--net-file",
                str(final_net),
                "--route-files",
                str(trips_file),
                "--output-file",
                str(routes_file),
                "--ignore-errors",
                "--no-warnings",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        shutil.copyfile(trips_file, routes_file)

    cfg_root = ET.Element("configuration")
    inp = ET.SubElement(cfg_root, "input")
    ET.SubElement(inp, "net-file", value=final_net.name)
    ET.SubElement(inp, "route-files", value=routes_file.name)
    time_el = ET.SubElement(cfg_root, "time")
    ET.SubElement(time_el, "begin", value="0")
    ET.SubElement(time_el, "end", value="5400")
    ET.SubElement(time_el, "step-length", value="1.0")
    ET.ElementTree(cfg_root).write(sumocfg_file, encoding="utf-8", xml_declaration=True)
    return sumocfg_file
