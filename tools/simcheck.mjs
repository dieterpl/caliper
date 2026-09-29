// Headless Rapier run of out/scene.json to verify moving designs without a browser.
//
// It mirrors web/src/viewer/physics.js exactly: same gravity/timestep/solver
// settings, same convex-hull colliders (from out/collision.json, which export.py
// writes from the very same trimesh the GLB is built from), same motor dispatch,
// same drives.
// If this and the browser ever disagree, one of the two has drifted.
//
//   node tools/simcheck.mjs [--seconds 6] [--static] [--quiet]
//
// --static holds every servo at its gait offset (no swing), which answers "does
// it stand?" separately from "does it walk?".
//
// It also reports SELF-COLLISION: any pair of bodies that touched which is not a
// foot on the floor. Without it a robot that walks through its own leg passes
// every other test here in silence. Two things it cannot see, which is why
// tools/collide.py exists as well and is not redundant with this:
//
//   * jointed pairs have their contacts disabled below (setContactsEnabled), so
//     a link driven into its own parent registers nothing here, and
//   * `decor` never becomes a collider at all, so belts, pulleys and motor cans
//     are invisible to Rapier. The Python sweep is the only thing that sees the
//     drivetrain.
//
// This is the one place where this file deliberately does MORE than
// web/src/viewer/physics.js: the browser shows contact by drawing it. Drive
// dispatch, which is what the two must agree about, is untouched.
import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join, parse } from 'node:path';

// Same root rule as tools/paths.py: $WORKSPACE, else the nearest ancestor of
// cwd holding cad/, else this file's grandparent (running from a checkout).
const HERE = dirname(fileURLToPath(import.meta.url));
function findRoot() {
  if (process.env.WORKSPACE) return process.env.WORKSPACE;
  let dir = process.cwd();
  for (;;) {
    if (existsSync(join(dir, 'cad'))) return dir;
    const up = parse(dir).dir;
    if (up === dir) return join(HERE, '..');
    dir = up;
  }
}
const ROOT = findRoot();
// Rapier ships with the app, not with the model — in the container the tools
// live in the image while ROOT is a workspace that has no web/ at all.
const RAPIER_PATH = process.env.RAPIER_PATH
  || [join(ROOT, 'web/vendor/rapier.es.js'), join(HERE, '../web/vendor/rapier.es.js')]
     .find(existsSync);
if (!RAPIER_PATH) {
  console.error('simcheck: cannot find rapier.es.js — set RAPIER_PATH');
  process.exit(2);
}
const RAPIER = (await import(RAPIER_PATH)).default;

const argv = process.argv.slice(2);
const flag = (n, d) => {
  const i = argv.indexOf(n);
  return i === -1 ? d : Number(argv[i + 1]);
};
const SECONDS = flag('--seconds', 6);
const GAIN = flag('--gain', 1);       // scales every servo stiffness/damping, for tuning
const AMP = flag('--amp', 1);         // scales every gait amplitude
const PERIOD = flag('--period', 0);   // overrides stride period (0 = use the model's)
const STATIC = argv.includes('--static');
const QUIET = argv.includes('--quiet');
const TAU = Math.PI * 2;

const scene = JSON.parse(readFileSync(join(ROOT, 'out/scene.json'), 'utf8'));
const hulls = JSON.parse(readFileSync(join(ROOT, 'out/collision.json'), 'utf8'));
const S = { timestep: 1 / 240, substeps: 4, gravity: -2000, solver_iters: 8, ...(scene.settings || {}) };
if (argv.includes('--gravity')) S.gravity = flag('--gravity', S.gravity);

await RAPIER.init();
const world = new RAPIER.World({ x: 0, y: 0, z: S.gravity });
world.timestep = S.timestep;
world.integrationParameters.numSolverIterations = S.solver_iters;

// ------------------------------------------------------------------ bodies --
const map = new Map();
const byCollider = new Map();   // collider handle -> body name, for contact events
for (const b of scene.bodies) {
  const [ox, oy, oz] = b.origin;
  let desc;
  if (b.type === 'fixed') desc = RAPIER.RigidBodyDesc.fixed();
  else if (b.type === 'kinematic') desc = RAPIER.RigidBodyDesc.kinematicPositionBased();
  else desc = RAPIER.RigidBodyDesc.dynamic();
  desc.setTranslation(ox, oy, oz);
  const rb = world.createRigidBody(desc);

  const pts = Float32Array.from(hulls[b.name] || []);
  const cdesc = RAPIER.ColliderDesc.convexHull(pts) || RAPIER.ColliderDesc.cuboid(5, 5, 5);
  cdesc.setFriction(b.friction ?? 0.7);
  cdesc.setRestitution(0.0);
  if (b.mass) cdesc.setMass(b.mass);
  cdesc.setActiveEvents(RAPIER.ActiveEvents.COLLISION_EVENTS);
  const col = world.createCollider(cdesc, rb);
  byCollider.set(col.handle, b.name);
  map.set(b.name, { rb, pts });
}

// ------------------------------------------------------------------ joints --
const joints = [];
for (const j of scene.joints) {
  const a = map.get(j.a), b = map.get(j.b);
  if (!a || !b) continue;
  const oa = scene.bodies.find((x) => x.name === j.a).origin;
  const ob = scene.bodies.find((x) => x.name === j.b).origin;
  const a1 = { x: j.anchor[0] - oa[0], y: j.anchor[1] - oa[1], z: j.anchor[2] - oa[2] };
  const a2 = { x: j.anchor[0] - ob[0], y: j.anchor[1] - ob[1], z: j.anchor[2] - ob[2] };
  const axis = { x: j.axis[0], y: j.axis[1], z: j.axis[2] };

  let params;
  if (j.type === 'revolute') params = RAPIER.JointData.revolute(a1, a2, axis);
  else if (j.type === 'prismatic') params = RAPIER.JointData.prismatic(a1, a2, axis);
  else params = RAPIER.JointData.fixed(a1, { w: 1, x: 0, y: 0, z: 0 }, a2, { w: 1, x: 0, y: 0, z: 0 });
  if (j.limits && params.limitsEnabled !== undefined) {
    params.limitsEnabled = true;
    params.limits = [j.limits[0], j.limits[1]];
  }

  const joint = world.createImpulseJoint(params, a.rb, b.rb, true);
  if (typeof joint.setContactsEnabled === 'function') joint.setContactsEnabled(false);
  joints.push({ joint, spec: j });
}

function applyMotor(joint, m, target) {
  if (!m) return;
  if (m.stiffness > 0) {
    if (typeof joint.configureMotorModel === 'function') {
      joint.configureMotorModel(RAPIER.MotorModel.AccelerationBased);
    }
    joint.configureMotorPosition(target || 0, m.stiffness * GAIN, (m.damping || 1.0) * GAIN);
  } else {
    joint.configureMotorVelocity(m.target_vel || 0, m.damping || 1.0);
  }
}
for (const { joint, spec } of joints) applyMotor(joint, spec.motor, spec.motor?.target_pos);

// Identical in behaviour to Physics.applyDrives + driveTarget in
// web/src/viewer/physics.js.
// The tuning flags are the only difference, and --static/--amp are no-ops for a
// sampled path: you cannot scale a foot trajectory by scaling one number, so
// --static holds each joint at its own stride mean instead.
function applyDrives(t) {
  for (const { joint, spec } of joints) {
    const d = spec.drive;
    if (!d || !spec.motor) continue;
    const period = PERIOD || d.period;
    const u = ((t / period + d.phase) % 1 + 1) % 1;
    let target;
    if (d.samples && d.samples.length) {
      const n = d.samples.length;
      if (STATIC) {
        target = d.samples.reduce((a, b) => a + b, 0) / n;
      } else {
        const f = u * n, i = Math.floor(f), a = f - i;
        target = d.samples[i % n] * (1 - a) + d.samples[(i + 1) % n] * a;
      }
    } else {
      target = d.offset + (STATIC ? 0 : d.amplitude * AMP) * Math.sin(TAU * u);
    }
    // Blend out of the built rest pose. Joint zero is the standing crouch, so
    // scaling the target is a straight interpolation from standing to walking.
    if (!STATIC && S.gait_ramp > 0) target *= Math.min(1, t / S.gait_ramp);
    applyMotor(joint, spec.motor, target);
  }
}

// ------------------------------------------------------------------ probes --
const chassis = map.get('chassis');
const feet = scene.bodies.filter((b) => b.name.endsWith('_lower')).map((b) => b.name);

// Lowest world-z of a body's hull — exact foot clearance, no hardcoded offsets.
function lowestZ(name) {
  const { rb, pts } = map.get(name);
  const p = rb.translation(), q = rb.rotation();
  let min = Infinity;
  for (let i = 0; i < pts.length; i += 3) {
    const x = pts[i], y = pts[i + 1], z = pts[i + 2];
    // v' = v + w*(2*cross(qv,v)) + cross(qv, 2*cross(qv,v)); only z is needed.
    const tx = 2 * (q.y * z - q.z * y);
    const ty = 2 * (q.z * x - q.x * z);
    const tz = 2 * (q.x * y - q.y * x);
    const wz = z + q.w * tz + (q.x * ty - q.y * tx);
    min = Math.min(min, wz + p.z);
  }
  return min;
}

// Yaw matters as much as roll and pitch: nothing here steers, so any heading the
// robot picks up early it keeps, and a machine crabbing 40 degrees off course
// still satisfies a "did it move forward" test.
function rollPitchYaw() {
  const q = chassis.rb.rotation();
  const sinp = 2 * (q.w * q.y - q.z * q.x);
  const pitch = Math.abs(sinp) >= 1 ? Math.sign(sinp) * Math.PI / 2 : Math.asin(sinp);
  const roll = Math.atan2(2 * (q.w * q.x + q.y * q.z), 1 - 2 * (q.x * q.x + q.y * q.y));
  const yaw = Math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z));
  return [roll, pitch, yaw];
}

// A foot on the floor is the point of the exercise. Everything else that touches
// is the robot hitting itself or falling on its chin.
//
// "Foot" is read off the joint graph rather than a name: a body no other body
// hangs from is the end of its chain, which is what stands on the floor. The
// tools are shared by every workspace, so a rule like `name.endsWith('_lower')`
// would only ever be right about the model it was written for.
const PARENTS = new Set((scene.joints || []).map((j) => j.a));
const isFoot = (name) => !PARENTS.has(name) && name !== 'ground';

function expected(a, b) {
  const [x, y] = [a, b].sort();
  return y === 'ground' && isFoot(x);
}

const contacts = new Map();     // "a × b" -> { a, b, first, steps }
const queue = new RAPIER.EventQueue(true);

function drainContacts(t) {
  queue.drainCollisionEvents((h1, h2, started) => {
    if (!started) return;   // onsets only: a pair that stays touching reports once
    const a = byCollider.get(h1), b = byCollider.get(h2);
    if (a === undefined || b === undefined || expected(a, b)) return;
    const key = [a, b].sort().join(' × ');
    const hit = contacts.get(key);
    if (hit) hit.steps += 1;
    else contacts.set(key, { a, b, first: t, steps: 1 });
  });
}

// --------------------------------------------------------------------- run --
const start = { ...chassis.rb.translation() };
const totalSteps = Math.round(SECONDS / S.timestep);
const sampleEvery = Math.round(0.25 / S.timestep);
const zs = [];
let t = 0, maxRoll = 0, maxPitch = 0, yaw = 0;

if (!QUIET) console.log(` t(s)     x       y       z    roll   pitch     yaw   feet(min z)`);
for (let i = 0; i < totalSteps; i++) {
  applyDrives(t);
  world.step(queue);
  drainContacts(t);
  t += S.timestep;

  let roll, pitch;
  [roll, pitch, yaw] = rollPitchYaw();
  maxRoll = Math.max(maxRoll, Math.abs(roll));
  maxPitch = Math.max(maxPitch, Math.abs(pitch));
  const p = chassis.rb.translation();
  if (t > SECONDS / 2) zs.push(p.z);

  if (!QUIET && i % sampleEvery === 0) {
    const fz = feet.map((f) => lowestZ(f).toFixed(0).padStart(4)).join(' ');
    console.log(`${t.toFixed(2).padStart(5)} ${p.x.toFixed(1).padStart(7)} ${p.y.toFixed(1).padStart(7)}` +
      ` ${p.z.toFixed(1).padStart(7)} ${roll.toFixed(2).padStart(6)} ${pitch.toFixed(2).padStart(6)}` +
      ` ${yaw.toFixed(2).padStart(7)}   ${fz}`);
  }
}

// ----------------------------------------------------------------- verdict --
const end = chassis.rb.translation();
const zMin = Math.min(...zs), zMax = Math.max(...zs);
const dx = end.x - start.x, dy = end.y - start.y;

console.log(`\n--- ${STATIC ? 'STATIC (servos held)' : 'GAIT'} · ${SECONDS}s ---`);
console.log(`chassis z   : ${start.z.toFixed(1)} -> ${end.z.toFixed(1)}  (2nd half range ${(zMax - zMin).toFixed(1)} mm)`);
console.log(`travel      : dx ${dx.toFixed(1)} mm   dy ${dy.toFixed(1)} mm`);
console.log(`max |roll|  : ${maxRoll.toFixed(3)} rad   max |pitch|: ${maxPitch.toFixed(3)} rad`);
// Course = where it actually went; yaw = where it is pointing. They separate a
// robot that turned from one that walked forwards while sliding sideways. Only
// meaningful once it has gone somewhere -- on a standing robot it is noise.
const path = Math.hypot(dx, dy);
if (path > 100) {
  console.log(`course      : ${(Math.atan2(dy, dx) * 180 / Math.PI).toFixed(1)}° off +X` +
    `   final yaw ${(yaw * 180 / Math.PI).toFixed(1)}°` +
    `   drift ${(Math.abs(dy) / path * 100).toFixed(1)}% of path`);
}

const upright = maxRoll < 0.5 && maxPitch < 0.5;
const standing = end.z > 100;
console.log(`\nupright     : ${upright ? 'PASS' : 'FAIL'}`);
console.log(`standing    : ${standing ? 'PASS' : `FAIL (collapsed to ${end.z.toFixed(1)} mm)`}`);
if (!STATIC) console.log(`walking     : ${Math.abs(dx) > 40 ? `PASS (${dx.toFixed(0)} mm)` : `FAIL (${dx.toFixed(0)} mm)`}`);

const clashes = [...contacts.values()].sort((p, q) => q.steps - p.steps);
if (!clashes.length) {
  console.log(`self-collide: PASS`);
} else {
  console.log(`self-collide: FAIL (${clashes.length} pair(s))`);
  for (const c of clashes) {
    console.log(`              ${c.a} × ${c.b}  from t=${c.first.toFixed(2)}s, ${c.steps} onset(s)`);
  }
}
