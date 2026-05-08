class LoamPanel extends HTMLElement {
  connectedCallback() {
    if (this._initialized) return;
    this._initialized = true;
    Object.assign(this.style, { display: "block", width: "100%", height: "100%" });
    const iframe = document.createElement("iframe");
    Object.assign(iframe.style, { width: "100%", height: "100%", border: "none", display: "block" });
    iframe.src = "/loam_frontend/loam-panel.html";
    this.appendChild(iframe);
  }
}
customElements.define("loam-panel", LoamPanel);
