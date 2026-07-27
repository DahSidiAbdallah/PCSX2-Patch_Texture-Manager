// Shared input-mode manager for the PS2-style navigation pages: polls the
// Gamepad API each frame and tracks whether the user's last touch was the
// keyboard/mouse or a controller, so each page can swap its on-screen prompt
// glyphs live instead of guessing which one is plugged in.
//
// Chromium mapping ("standard" gamepad layout, what Xbox controllers map to):
//   buttons: 0=A 1=B 2=X 3=Y  4=LB 5=RB  12=D-pad Up 13=Down 14=Left 15=Right
//   axes: 0 = left stick X (-1 left .. 1 right), 1 = left stick Y (-1 up .. 1 down)
export class InputManager {
  constructor() {
    this.mode = 'keyboard'; // 'keyboard' | 'gamepad'
    this._modeListeners = [];
    this._confirmHandlers = [];
    this._backHandlers = [];
    this._dirHandlers = { up: [], down: [], left: [], right: [] };
    this._shoulderHandlers = { l: [], r: [] };
    this._buttonHandlers = {}; // index -> [cb, ...], for one-off bindings (e.g. Y)
    this._prevButtons = {};
    this._repeatAt = {};
    this._heldDir = { x: 0, y: 0 };

    // Any real keyboard/mouse touch means the user is back on keyboard,
    // even mid-session with a controller connected.
    window.addEventListener('keydown', () => this._setMode('keyboard'));
    window.addEventListener('mousedown', () => this._setMode('keyboard'));

    this._poll = this._poll.bind(this);
    requestAnimationFrame(this._poll);
  }

  onModeChange(cb) { this._modeListeners.push(cb); }
  onConfirm(cb) { this._confirmHandlers.push(cb); }
  onBack(cb) { this._backHandlers.push(cb); }
  onUp(cb) { this._dirHandlers.up.push(cb); }
  onDown(cb) { this._dirHandlers.down.push(cb); }
  onLeft(cb) { this._dirHandlers.left.push(cb); }
  onRight(cb) { this._dirHandlers.right.push(cb); }
  onShoulderL(cb) { this._shoulderHandlers.l.push(cb); }
  onShoulderR(cb) { this._shoulderHandlers.r.push(cb); }
  // Generic escape hatch for one-off button bindings (e.g. Y = button 3)
  // that don't warrant a dedicated named method.
  onButton(index, cb) { (this._buttonHandlers[index] = this._buttonHandlers[index] || []).push(cb); }

  _setMode(mode) {
    if (this.mode === mode) return;
    this.mode = mode;
    this._modeListeners.forEach((cb) => cb(mode));
  }

  _poll() {
    requestAnimationFrame(this._poll);
    const pads = navigator.getGamepads ? navigator.getGamepads() : [];
    let pad = null;
    for (const p of pads) { if (p) { pad = p; break; } }
    if (!pad) return;

    const isPressed = (i) => !!(pad.buttons[i] && pad.buttons[i].pressed);
    const justPressed = (i) => isPressed(i) && !this._prevButtons[i];

    if (justPressed(0)) { this._setMode('gamepad'); this._confirmHandlers.forEach((cb) => cb()); }
    if (justPressed(1)) { this._setMode('gamepad'); this._backHandlers.forEach((cb) => cb()); }
    if (justPressed(4)) { this._setMode('gamepad'); this._shoulderHandlers.l.forEach((cb) => cb()); }
    if (justPressed(5)) { this._setMode('gamepad'); this._shoulderHandlers.r.forEach((cb) => cb()); }
    for (const idx of Object.keys(this._buttonHandlers)) {
      if (justPressed(Number(idx))) {
        this._setMode('gamepad');
        this._buttonHandlers[idx].forEach((cb) => cb());
      }
    }

    const axisX = pad.axes[0] || 0;
    const axisY = pad.axes[1] || 0;
    const now = performance.now();
    this._pollAxis('x', isPressed(14) ? -1 : isPressed(15) ? 1 : (axisX < -0.5 ? -1 : axisX > 0.5 ? 1 : 0),
      { [-1]: 'left', [1]: 'right' }, now);
    this._pollAxis('y', isPressed(12) ? -1 : isPressed(13) ? 1 : (axisY < -0.5 ? -1 : axisY > 0.5 ? 1 : 0),
      { [-1]: 'up', [1]: 'down' }, now);

    for (let i = 0; i < pad.buttons.length; i++) this._prevButtons[i] = isPressed(i);
  }

  _pollAxis(axis, dir, dirNames, now) {
    if (dir !== 0) {
      this._setMode('gamepad');
      const key = dirNames[dir];
      // Fire immediately on a fresh press, then repeat on hold.
      if (this._heldDir[axis] !== dir || now - (this._repeatAt[key] || 0) > 260) {
        this._dirHandlers[key].forEach((cb) => cb());
        this._repeatAt[key] = now;
      }
      this._heldDir[axis] = dir;
    } else {
      this._heldDir[axis] = 0;
    }
  }
}
