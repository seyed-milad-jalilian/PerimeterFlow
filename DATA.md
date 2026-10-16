# Data Licenses & Citations

This repository contains **no bundled datasets**. All external data must be
obtained by the user under the terms below. `data/amsterdam_subset/` is an
empty placeholder: it exists so that a user who has lawfully obtained the
Amsterdam urban traffic data has a documented location to place a working
subset. Do not commit raw municipal measurement files unless the license terms
you received with the export explicitly permit redistribution.

## Amsterdam Urban Traffic Trajectories (NDW & Gemeente Amsterdam Open Data)

**Citation.**

> Nationale Databank Wegverkeersgegevens (NDW) & Gemeente Amsterdam.
> *Amsterdam Urban Traffic Trajectories* — empirical multi-sensor arterial and
> loop/probe trajectory logs from Amsterdam's urban road network, Netherlands.
> https://opendata.ndw.nu / https://data.amsterdam.nl

**Access and license.** License: CC BY 4.0 / Open Data Commons (Official
Municipal Transport Open Data). Terms: non-commercial open scientific research;
deterministic trajectory slices generated via open municipal sensor logs.
Attribution of NDW and the Gemeente Amsterdam as data sources is required in
any derivative work or publication. Raw bulk exports are not redistributed in
git; the automated fetch/checksum verification script processes local CSV
slices only. The exact license text distributed with the export at download
time is authoritative — consult and comply with it before use.

**Role in this project.** The Amsterdam Urban Traffic Trajectories benchmark is
used for *offline empirical validation of sparse MFD accumulation estimation
only*. Closed-loop perimeter control cannot be actuated on historical offline
logs; this limitation is documented in `docs/THREATS_TO_VALIDITY.md`.

## SUMO (Simulation of Urban MObility)

**License.** Eclipse Public License 2.0 (EPL-2.0). SUMO is an external
simulator; this repository does not include or redistribute SUMO source code.
Users must install SUMO separately and comply with EPL-2.0.

**Citation.**

> Lopez, P. A., Behrisch, M., Bieker-Walz, L., Erdmann, J., Flötteröd, Y.-P.,
> Hilbrich, R., Lücken, L., Rummel, J., Wagner, P., & Wießner, E. (2018).
> Microscopic Traffic Simulation using SUMO. In *Proceedings of the 21st IEEE
> International Conference on Intelligent Transportation Systems (ITSC)*,
> pp. 2575–2582. IEEE.

**Role in this project.** SUMO provides the synthetic two-reservoir network,
the closed-loop simulation episodes, and the 100%-known ground-truth
trajectories from which sparse probe observations are derived.

## Generated artifacts

JSON result artifacts under `results/` carry an explicit `license` field
(enforced by `data/schemas/mfd_artifact.schema.json`) so that every published
result document states its own terms at the point of use. Repository-level code
licensing is recorded at the repository root.

## Golden parity vectors (`data/golden/`)

**License.** MIT (same as the repository code).

**Role in this project.** Deterministic verification vectors exported from
seeded `Mulberry32` runs and committed in the repository, used to assert
numerical parity (tolerance $\le 10^{-9}$) between the Python core and the
TypeScript browser Web Worker implementation.

## Placeholder directories

- `data/golden/` — holds exported deterministic parity vectors once the
  simulation core exists; the directory is currently kept only by `.gitkeep`.
- `data/amsterdam_subset/` — intentionally empty until a user places a
  license-compliant Amsterdam urban traffic trajectory subset here.
- `results/` — destination for hash-stamped, schema-validated experiment
  artifacts produced by real runs.
