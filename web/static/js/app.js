/* DroneBuilder Web UI — minimal JS helpers */

// Confirm dialogs for destructive actions
document.addEventListener("click", function (e) {
  var btn = e.target.closest("[data-confirm]");
  if (btn && !confirm(btn.dataset.confirm)) {
    e.preventDefault();
    e.stopImmediatePropagation();
  }
});

// Auto-dismiss flash messages after 4 seconds
document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll(".flash").forEach(function (el) {
    setTimeout(function () {
      el.style.transition = "opacity 0.3s";
      el.style.opacity = "0";
      setTimeout(function () { el.remove(); }, 300);
    }, 4000);
  });
});
