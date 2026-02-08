// beautiful-mermaid initialization for canVODpy docs
// Renders mermaid diagrams with a Nord-inspired palette via beautiful-mermaid.

document.addEventListener("DOMContentLoaded", function () {
  if (!window.beautifulMermaid) return;

  // Zensical renders ```mermaid blocks as <pre class="mermaid"><code>…</code></pre>
  const blocks = document.querySelectorAll("pre.mermaid");
  blocks.forEach(async (pre) => {
    const code = pre.querySelector("code");
    const definition = (code || pre).textContent.trim();
    if (!definition) return;
    try {
      const svg = await window.beautifulMermaid.renderMermaid(definition, {
        theme: {
          background: "transparent",
          foreground: "#183128",
          accent: "#375D3B",
          muted: "#ABC8A4",
        },
      });
      const container = document.createElement("div");
      container.className = "mermaid-rendered";
      container.innerHTML = svg;
      pre.replaceWith(container);
    } catch (_) {
      // Fall back — leave the raw <pre> in place for native mermaid.js
    }
  });
});
