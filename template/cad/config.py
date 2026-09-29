"""Every dimension, mass and gain of this design, in one place.

Change a number here and the watcher re-exports; the browser shows it within a
second. Geometry lives in `parts/`, assembly order in `model.py` — so a change
of PROPORTION is a change here, and a change of SHAPE is a change there.

Units are millimetres, Z up. The robot is authored STANDING with its feet
exactly on z=0, so every joint's zero is "stand" and a servo target is a plain
deviation from it.
"""

# ------------------------------------------------------------------ frame ----
BODY_L = 220.0        # front to back
BODY_W = 130.0        # side to side
BODY_H = 44.0         # deck thickness
BODY_R = 8.0          # edge radius

HIP_X = BODY_L / 2 - 24.0   # how far fore/aft the hips sit from the centre
HIP_Y = BODY_W / 2          # hips at the body's sides

# ------------------------------------------------------------------- legs ----
THIGH_L = 110.0
SHANK_L = 110.0
LINK_R = 13.0         # thigh radius; the shank is drawn a little slimmer
FOOT_R = 16.0

# Derived heights. The foot is a sphere resting ON the floor, so its centre —
# not its bottom — is one radius up, and everything stacks from there.
KNEE_Z = FOOT_R + SHANK_L        # 126
HIP_Z = KNEE_Z + THIGH_L         # 236
BODY_Z = HIP_Z + BODY_H / 2      # 258

# ------------------------------------------------------------------ masses ----
M_BODY = 3.0
M_THIGH = 0.35
M_SHANK = 0.25

# ------------------------------------------------------------------- gains ----
# Acceleration-based, so these are mass-independent — and they are not small
# numbers. A position servo (stiffness > 0) is what holds a pose against
# gravity; a velocity motor can only brake, so a limbed model on target_vel=0
# folds flat. Sweep with `caliper sim --gain 2` rather than guessing.
SERVO_STIFF = 9.0e4
SERVO_DAMP = 4.5e3

# Radians. Zero is the standing pose authored above; the knee only folds one way.
HIP_LIMITS = (-0.9, 0.9)
KNEE_LIMITS = (-2.0, 0.05)

# ------------------------------------------------------------------ colours ----
C_BODY = "#2f4f7f"
C_LINK = "#94a3b8"
C_FOOT = "#0f172a"
C_GROUND = "#1e293b"
