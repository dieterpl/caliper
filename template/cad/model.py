"""The assembly — build order only.

Dimensions live in `config.py`, geometry in `parts/`. This file says what the
machine is made of and nothing else, so a change of shape is a change to a part
module and a change of proportion is a change to config.

Right now: a four-legged stander. It holds its pose and does not walk — give it
a gait by passing `drive=` to the joints in `parts/leg.py` (see CLAUDE.md).
"""

from parts.chassis import chassis
from parts.ground import ground
from parts.leg import leg
from scene import sim

sim(timestep=1 / 240, substeps=4, solver_iters=8)

ground()
chassis()

#    sx: +1 front / -1 back      sy: +1 left / -1 right
leg("fl", +1, +1)
leg("fr", +1, -1)
leg("bl", -1, +1)
leg("br", -1, -1)
