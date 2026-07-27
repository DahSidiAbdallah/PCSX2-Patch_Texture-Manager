// Shared input-mode manager for the PS2-style navigation pages: polls the
// Gamepad API each frame and tracks whether the user's last touch was the
// keyboard/mouse or a controller, so each page can swap its on-screen prompt
// glyphs live instead of guessing which one is plugged in.
//
// Chromium mapping ("standard" gamepad layout, what Xbox controllers map to):
//   buttons: 0=A 1=B 2=X 3=Y  12=D-pad Up 13=Down 14=Left 15=Right  9=Menu
//   axes: 0 = left stick X (-1 left .. 1 right)
export class InputManager {
  constructor() {
    this.mode = 'keyboard'; // 'keyboard' | 'gamepad'
    this._modeListeners = [];
    this._confirmHandlers = [];
    this._backHandlers = [];
    this._leftHandlers = [];
    this._rightHandlers = [];
    this._prevButtons = {};
    this._repeatAt = { left: 0, right: 0 };
    this._heldDir = 0;

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
  onLeft(cb) { this._leftHandlers.push(cb); }
  onRight(cb) { this._rightHandlers.push(cb); }

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

    const axisX = pad.axes[0] || 0;
    const goLeft = isPressed(14) || axisX < -0.5;
    const goRight = isPressed(15) || axisX > 0.5;
    const now = performance.now();
    if (goLeft || goRight) {
      this._setMode('gamepad');
      const dir = goLeft ? -1 : 1;
      const key = goLeft ? 'left' : 'right';
      // Fire immediately on a fresh press, then repeat on hold.
      if (this._heldDir !== dir || now - this._repeatAt[key] > 260) {
        (goLeft ? this._leftHandlers : this._rightHandlers).forEach((cb) => cb());
        this._repeatAt[key] = now;
      }
      this._heldDir = dir;
    } else {
      this._heldDir = 0;
    }

    for (let i = 0; i < pad.buttons.length; i++) this._prevButtons[i] = isPressed(i);
  }
}
