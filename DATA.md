# Data Licenses & Citations

This repository contains **no bundled datasets**. All external data must be
obtained by the user under the terms below. `data/pneuma_subset/` is an empty
placeholder: it exists so that a user who has lawfully obtained the pNEUMA
dataset has a documented location to place a working subset. Do not commit raw
pNEUMA data unless the license terms you received with the dataset explicitly
permit redistribution.

## pNEUMA (naturalistic drone trajectories, downtown Athens)

**Citation.**

> Barmpounakis, E., & Geroliminis, N. (2020). On the new era of urban traffic
> monitoring with massive drone data: The pNEUMA large-scale field experiment.
> *Transportation Research Part C: Emerging Technologies*, 111, 50–71.

**Access and license.** The pNEUMA dataset is distributed by its authors
(URBAN Mobility Systems Lab, EPFL) to researchers upon registration through the
official dataset portal. It is offered under Creative Commons Attribution
(CC-BY) terms: attribution of the source dataset and its authors is required in
any derivative work or publication. The exact license text distributed with the
dataset at download time is authoritative — consult and comply with it before
use, as access conditions (registration, research-use clauses) may apply and
redistribution may be restricted.

**Role in this project.** pNEUMA is used for *offline replay validation of the
estimation stack only*. Closed-loop perimeter control cannot be actuated on
recorded trajectories; this limitation is documented in
`docs/THREATS_TO_VALIDITY.md`.

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

## Placeholder directories

- `data/golden/` — holds exported deterministic parity vectors once the
  simulation core exists; the directory is currently kept only by `.gitkeep`.
- `data/pneuma_subset/` — intentionally empty until a user places a
  license-compliant pNEUMA subset here.
- `results/` — destination for hash-stamped, schema-validated experiment
  artifacts produced by real runs.
