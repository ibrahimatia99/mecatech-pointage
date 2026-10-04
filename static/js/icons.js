(function () {
  const icons = {
    "bolt": '<path d="M13 2 4 14h6l-1 8 9-12h-6l1-8Z"/>',
    "chart-pie": '<path d="M12 3v9h9"/><path d="M21 12a9 9 0 1 1-9-9"/>',
    "users": '<circle cx="9" cy="8" r="3"/><path d="M3 20c.5-3.3 2.4-5 6-5s5.5 1.7 6 5"/><path d="M16 5.5a3 3 0 0 1 0 5.8M17 15c2.7.2 4.2 1.8 4.8 5"/>',
    "gear": '<path d="m12 2 1 2.2 2.3.9 2.1-1.1 1.6 1.6-1.1 2.1.9 2.3L21 11v2l-2.2 1-.9 2.3 1.1 2.1-1.6 1.6-2.1-1.1-2.3.9L11 22h2l-1-2.2-2.3-.9-2.1 1.1-1.6-1.6 1.1-2.1-.9-2.3L3 13v-2l2.2-1 .9-2.3L5 5.6 6.6 4l2.1 1.1L11 4.2 12 2Z"/><circle cx="12" cy="12" r="3"/>',
    "gears": '<circle cx="8" cy="9" r="3"/><path d="M8 4v2M8 12v2M3 9h2m6 0h2M4.5 5.5 6 7m4 4 1.5 1.5M4.5 12.5 6 11m4-4 1.5-1.5"/><circle cx="17" cy="16" r="3"/><path d="M17 11v2M17 19v2M12 16h2m6 0h2M13.5 12.5 15 14m4 4 1.5 1.5M13.5 19.5 15 18m4-4 1.5-1.5"/>',
    "right-from-bracket": '<path d="M14 8l4 4-4 4M18 12H5"/><path d="M12 4H4v16h8"/>',
    "arrow-right-from-bracket": '<path d="m13 8 4 4-4 4M17 12H5"/><path d="M13 4h7v16h-7"/>',
    "arrow-right-to-bracket": '<path d="m11 8-4 4 4 4M7 12h12"/><path d="M11 4H4v16h7"/>',
    "mask": '<path d="M3 7c3-2 15-2 18 0v5c-1 4-4 6-6 6l-3-2-3 2c-2 0-5-2-6-6V7Z"/><circle cx="8" cy="11" r="1"/><circle cx="16" cy="11" r="1"/>',
    "check": '<path d="m5 12 4 4L19 6"/>',
    "trash": '<path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5"/>',
    "id-card": '<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="8" cy="11" r="2"/><path d="M13 10h5M13 14h5"/>',
    "id-card-clip": '<rect x="4" y="5" width="16" height="14" rx="2"/><path d="M9 5V3h6v2M8 10h8M8 14h5"/>',
    "file-pdf": '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v5h5M9 15h6M9 18h4"/>',
    "file-lines": '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v5h5M9 12h6M9 16h6"/>',
    "pen": '<path d="m4 20 4.5-1 10-10a2.1 2.1 0 0 0-3-3l-10 10L4 20Z"/><path d="m13 7 4 4"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "user-plus": '<circle cx="9" cy="8" r="3"/><path d="M3 20c.5-3.3 2.4-5 6-5s5.5 1.7 6 5M19 8v6M16 11h6"/>',
    "user-pen": '<circle cx="9" cy="8" r="3"/><path d="M3 20c.5-3.3 2.4-5 6-5 2 0 3.5.5 4.5 1.5M15 19l4.5-4.5 2 2L17 21h-2z"/>',
    "floppy-disk": '<path d="M5 3h12l4 4v14H3V3z"/><path d="M7 3v6h8V3M7 21v-7h10v7"/>',
    "palette": '<path d="M12 3a9 9 0 0 0 0 18h1.5c1.2 0 2-.7 2-1.8 0-.8-.5-1.3-.9-1.8-.5-.6-.2-1.4.7-1.4H17a4 4 0 0 0 4-4C21 7.5 17 3 12 3Z"/><circle cx="7.5" cy="10" r="1"/><circle cx="10" cy="7" r="1"/><circle cx="14" cy="7" r="1"/>',
    "signature": '<path d="M4 17c3-5 4-7 6-7 2 0-1 5 1 5 2 0 3-4 5-4 2 0 0 4 2 4 1 0 2-.5 3-1"/><path d="M4 20h17"/>',
    "droplet": '<path d="M12 3s6 7 6 11a6 6 0 0 1-12 0c0-4 6-11 6-11Z"/>',
    "image": '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8" cy="9" r="1.5"/><path d="m4 17 5-5 4 4 2-2 5 5"/>',
    "icons": '<rect x="4" y="4" width="6" height="6" rx="1"/><rect x="14" y="4" width="6" height="6" rx="1"/><rect x="4" y="14" width="6" height="6" rx="1"/><rect x="14" y="14" width="6" height="6" rx="1"/>',
    "database": '<ellipse cx="12" cy="5" rx="7" ry="3"/><path d="M5 5v7c0 1.7 3.1 3 7 3s7-1.3 7-3V5M5 12v7c0 1.7 3.1 3 7 3s7-1.3 7-3v-7"/>',
    "key": '<circle cx="8" cy="15" r="4"/><path d="m11 12 8-8M16 5l3 3M14 7l3 3"/>',
    "clock-rotate-left": '<path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v6h6M12 7v5l3 2"/>',
    "folder-open": '<path d="M3 7h7l2 2h9v10H3z"/><path d="M3 7V5h6l2 2"/>',
    "filter": '<path d="M4 5h16l-6 7v6l-4 2v-8z"/>',
    "print": '<path d="M6 9V3h12v6M6 17H4a2 2 0 0 1-2-2v-4a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="7"/><path d="M17 12h1"/>',
    "arrow-left": '<path d="m12 19-7-7 7-7M5 12h14"/>',
    "arrow-right": '<path d="m12 5 7 7-7 7M19 12H5"/>',
    "menu": '<path d="M4 6h16M4 12h16M4 18h16"/>',
    "x": '<path d="M6 6l12 12M18 6 6 18"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "language": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18"/>',
    "play": '<path d="m9 6 10 6-10 6V6Z"/>',
    "shield-check": '<path d="M12 3 20 6v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3Z"/><path d="m8.5 12 2.2 2.2 4.8-5"/>'
  };

  function renderIcons(root) {
    (root || document).querySelectorAll('.offline-icon[data-icon]').forEach(el => {
      if (el.dataset.rendered === '1') return;
      const name = el.dataset.icon;
      const path = icons[name] || '<circle cx="12" cy="12" r="8"/><path d="M12 8v8M8 12h8"/>';
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('viewBox', '0 0 24 24');
      svg.setAttribute('fill', 'none');
      svg.setAttribute('stroke', 'currentColor');
      svg.setAttribute('stroke-width', '1.8');
      svg.setAttribute('stroke-linecap', 'round');
      svg.setAttribute('stroke-linejoin', 'round');
      svg.setAttribute('aria-hidden', 'true');
      svg.innerHTML = path;
      el.replaceChildren(svg);
      el.dataset.rendered = '1';
    });
  }

  window.renderOfflineIcons = renderIcons;
  document.addEventListener('DOMContentLoaded', () => renderIcons(document));
  const observer = new MutationObserver(mutations => {
    mutations.forEach(m => m.addedNodes.forEach(node => {
      if (node.nodeType === 1) renderIcons(node);
    }));
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });
})();
