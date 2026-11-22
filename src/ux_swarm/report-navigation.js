(() => {
  const menu = document.getElementById("contents");
  function reveal(hash) {
    const target = document.getElementById(hash.slice(1));
    if (!target) return;
    const details = target.matches("details") ? target : target.querySelector(":scope > details");
    if (details) details.open = true;
  }
  document.addEventListener("click", event => {
    if (!menu.contains(event.target) || event.target.closest("a")) menu.open = false;
    const link = event.target.closest('a[href^="#"]');
    if (link) reveal(link.hash);
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && menu.open) {
      menu.open = false;
      menu.querySelector("summary").focus();
    }
  });
  window.addEventListener("hashchange", () => reveal(location.hash));
  reveal(location.hash);
})();
