(() => {
  const dialog = document.querySelector("#player");
  const frame = dialog.querySelector("iframe");
  let playerUrl;
  let returnUrl;
  let opener;

  function syncLocation() {
    const hash = new URLSearchParams(location.hash.slice(1));
    if (!hash.has("session")) {
      if (dialog.open) {
        dialog.close();
        frame.removeAttribute("src");
        opener?.focus({preventScroll:true});
      }
      return;
    }
    if (!playerUrl) {
      const documentText = JSON.parse(document.querySelector("#player-document").textContent);
      playerUrl = URL.createObjectURL(new Blob([documentText], {type: "text/html;charset=utf-8"}));
    }
    frame.src = playerUrl + "#" + hash.toString();
    if (!dialog.open) dialog.showModal();
  }

  function closePlayer() {
    if (returnUrl) {
      history.back();
      returnUrl = undefined;
    } else {
      history.replaceState(null, "", location.href.split("#")[0] + "#overview");
      syncLocation();
      document.querySelector("h1").focus({preventScroll:true});
    }
  }

  document.addEventListener("click", (event) => {
    const link = event.target.closest("a[href^='#session=']");
    if (!link || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    opener = link;
    returnUrl = location.href;
  });
  document.querySelector("#close-player").addEventListener("click", closePlayer);
  dialog.addEventListener("cancel", (event) => {event.preventDefault(); closePlayer();});
  window.addEventListener("hashchange", syncLocation);
  syncLocation();
})();
