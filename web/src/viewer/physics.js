// Rapier world built from out/scene.json. Bodies use convex-hull colliders from
// the viewer's per-body local vertices; joints map to Rapier impulse joints with
// velocity motors OR position servos. CAD units are mm, so gravity is in mm/s^2.
//
// Joint handles are retained by name so that joints carrying a `drive` (a
// periodic target angle, see cad/scene.py:gait) can be re-commanded every step.
// That is what turns a pile of links into a walking robot.
import RAPIER from '@dimforge/rapier3d-compat';

const DEFAULTS = { timestep: 1 / 240, substeps: 4, gravity: -2000, solver_iters: 8, gait_ramp: 1.5 };
const TAU = Math.PI * 2;

/** Target angle of a drive at time `t`: a sampled path if it has one, else a sine.
 *  Sampled drives come from cad/gait.py, which solves IK along a foot path. */
export function driveTarget(d, t) {
  const u = ((t / d.period + d.phase) % 1 + 1) % 1;   // wrap, and stay positive
  if (d.samples && d.samples.length) {
    const n = d.samples.length;
    const f = u * n;
    const i = Math.floor(f);
    const a = f - i;
    return d.samples[i % n] * (1 - a) + d.samples[(i + 1) % n] * a;
  }
  return d.offset + d.amplitude * Math.sin(TAU * u);
}

let ready = null;
export function initPhysics() {
  if (!ready) ready = RAPIER.init();
  return ready;
}

export class Physics {
  constructor() {
    this.world = null;
    this.map = new Map();    // body name -> { rb, type }
    this.joints = new Map(); // joint name -> { joint, spec }
    this.time = 0;
    this.steps = 0;
    this.settings = { ...DEFAULTS };
  }

  // scene = parsed scene.json; bodies = viewer body map (for local vertices).
  build(scene, viewerBodies) {
    this.settings = { ...DEFAULTS, ...(scene.settings || {}) };
    this.world = new RAPIER.World({ x: 0, y: 0, z: this.settings.gravity });
    this.world.timestep = this.settings.timestep;
    this.world.integrationParameters.numSolverIterations = this.settings.solver_iters;
    this.map.clear();
    this.joints.clear();
    this.time = 0;
    this.steps = 0;

    for (const b of scene.bodies) {
      const [ox, oy, oz] = b.origin;
      let desc;
      if (b.type === 'fixed') desc = RAPIER.RigidBodyDesc.fixed();
      else if (b.type === 'kinematic') desc = RAPIER.RigidBodyDesc.kinematicPositionBased();
      else desc = RAPIER.RigidBodyDesc.dynamic();
      desc.setTranslation(ox, oy, oz);
      const rb = this.world.createRigidBody(desc);

      const cdesc = this._collider(b, viewerBodies);
      if (cdesc) {
        cdesc.setFriction(b.friction ?? 0.7);
        cdesc.setRestitution(0.0);
        if (b.mass) cdesc.setMass(b.mass);
        this.world.createCollider(cdesc, rb);
      }
      this.map.set(b.name, { rb, type: b.type });
    }

    for (const j of scene.joints) this._joint(scene, j);
    return this;
  }

  _collider(b, viewerBodies) {
    const vb = viewerBodies.get(b.name);
    if (!vb) return RAPIER.ColliderDesc.cuboid(5, 5, 5);
    const pts = vb.localVerts;
    if (b.collider === 'trimesh') {
      // build indices from the (already triangulated) vertex list
      const idx = new Uint32Array(pts.length / 3);
      for (let i = 0; i < idx.length; i++) idx[i] = i;
      return RAPIER.ColliderDesc.trimesh(pts, idx);
    }
    return RAPIER.ColliderDesc.convexHull(pts) || RAPIER.ColliderDesc.cuboid(5, 5, 5);
  }

  _joint(scene, j) {
    const a = this.map.get(j.a), b = this.map.get(j.b);
    if (!a || !b) return;
    const oa = scene.bodies.find((x) => x.name === j.a).origin;
    const ob = scene.bodies.find((x) => x.name === j.b).origin;
    const anchor1 = { x: j.anchor[0] - oa[0], y: j.anchor[1] - oa[1], z: j.anchor[2] - oa[2] };
    const anchor2 = { x: j.anchor[0] - ob[0], y: j.anchor[1] - ob[1], z: j.anchor[2] - ob[2] };
    const axis = { x: j.axis[0], y: j.axis[1], z: j.axis[2] };

    let params;
    if (j.type === 'revolute') params = RAPIER.JointData.revolute(anchor1, anchor2, axis);
    else if (j.type === 'prismatic') params = RAPIER.JointData.prismatic(anchor1, anchor2, axis);
    else params = RAPIER.JointData.fixed(anchor1, { w: 1, x: 0, y: 0, z: 0 }, anchor2, { w: 1, x: 0, y: 0, z: 0 });

    if (j.limits && params.limitsEnabled !== undefined) {
      params.limitsEnabled = true;
      params.limits = [j.limits[0], j.limits[1]];
    }

    const joint = this.world.createImpulseJoint(params, a.rb, b.rb, true);

    // Linked bodies overlap at every pivot (and the hip housings sit inside the
    // chassis). Without this their convex hulls fight the joint constraint and
    // the whole assembly jitters apart.
    if (typeof joint.setContactsEnabled === 'function') joint.setContactsEnabled(false);

    this.joints.set(j.name || `${j.a}->${j.b}`, { joint, spec: j });
    this._applyMotor(joint, j.motor, j.motor ? j.motor.target_pos : 0);
  }

  // stiffness > 0 -> PD position servo; otherwise the old velocity motor.
  _applyMotor(joint, m, target) {
    if (!m) return;
    if (m.stiffness > 0) {
      if (typeof joint.configureMotorPosition !== 'function') return;
      // AccelerationBased (Rapier's default) is mass-normalised, so gains do not
      // need retuning every time a link's mass changes.
      if (typeof joint.configureMotorModel === 'function') {
        joint.configureMotorModel(RAPIER.MotorModel.AccelerationBased);
      }
      joint.configureMotorPosition(target || 0, m.stiffness, m.damping || 1.0);
    } else if (typeof joint.configureMotorVelocity === 'function') {
      joint.configureMotorVelocity(m.target_vel || 0, m.damping || 1.0);
    }
  }

  // Re-command every driven joint for simulated time t.
  // NOTE: tools/simcheck.mjs carries an identical copy of this. If one changes
  // and the other does not, simcheck starts lying about what the browser does.
  applyDrives(t) {
    // Blend out of the built rest pose over the first `gait_ramp` seconds. A
    // trot starts its two diagonal pairs at opposite points of the stride, so
    // commanding the full gait at t=0 lands opposite step commands on them and
    // kicks the robot into a yaw it never recovers from -- nothing here steers.
    // Scaling the target works as a stand-to-walk blend only because joint zero
    // is the standing crouch the model is authored in (cad/parts/leg.py).
    const ramp = this.settings.gait_ramp > 0
      ? Math.min(1, t / this.settings.gait_ramp) : 1;
    for (const { joint, spec } of this.joints.values()) {
      const d = spec.drive;
      if (!d || !spec.motor) continue;
      this._applyMotor(joint, spec.motor, driveTarget(d, t) * ramp);
    }
  }

  step(substeps = this.settings.substeps) {
    if (!this.world) return;
    for (let i = 0; i < substeps; i++) {
      this.applyDrives(this.time);
      this.world.step();
      this.time += this.world.timestep;
      this.steps += 1;
    }
  }

  // -> [{ name, p:{x,y,z}, q:{x,y,z,w} }] for dynamic/kinematic bodies
  transforms() {
    const out = [];
    for (const [name, { rb, type }] of this.map) {
      if (type === 'fixed') continue;
      out.push({ name, p: rb.translation(), q: rb.rotation() });
    }
    return out;
  }
}
