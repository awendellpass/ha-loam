class LoamPanel extends HTMLElement {
  set hass(hass) {
    this._hass = hass;
    if (this._iframe && this._iframe.contentWindow) {
      this._iframe.contentWindow.postMessage(
        { type: "loam-auth", token: hass.auth.data.access_token },
        window.location.origin
      );
    }
  }

  connectedCallback() {
    if (this._initialized) return;
    this._initialized = true;
    this.style.cssText = "display:block;height:100vh;overflow:hidden;";
    const iframe = document.createElement("iframe");
    Object.assign(iframe.style, { width: "100%", height: "100%", border: "none", display: "block" });
    iframe.src = "/loam_frontend/loam-panel.html";
    this._iframe = iframe;
    iframe.addEventListener("load", () => {
      if (this._hass) {
        iframe.contentWindow.postMessage(
          { type: "loam-auth", token: this._hass.auth.data.access_token },
          window.location.origin
        );
      }
    });
    this.appendChild(iframe);
  }
}
customElements.define("loam-panel", LoamPanel);
