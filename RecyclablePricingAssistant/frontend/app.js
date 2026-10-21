(function () {
  const screens = document.querySelectorAll('.screen');
  const navBtns = document.querySelectorAll('nav button');
  const container = document.querySelector('.screens');

  function show(id) {
    screens.forEach(s => s.classList.toggle('active', s.id === id));
    // The detail screen belongs to the Inquiries tab
    const tab = id === 'detail' ? 'inquiries' : id;
    navBtns.forEach(b => b.classList.toggle('active', b.dataset.nav === tab));
    container.scrollTo({ top: 0 });
  }

  // Bottom nav switching
  navBtns.forEach(b => b.addEventListener('click', () => show(b.dataset.nav)));

  // Back button on detail screen
  document.getElementById('backBtn').addEventListener('click', () => show('inquiries'));

  // Inquiry card -> detail (Elena)
  document.querySelectorAll('.inq[data-open="detail"]').forEach(c =>
    c.addEventListener('click', () => show('detail'))
  );

  // Filter pills + search
  const cards = document.querySelectorAll('.inq');
  const pills = document.querySelectorAll('.pill');
  const searchInput = document.getElementById('searchInput');
  let filter = 'all';

  function applyFilters() {
    const q = searchInput.value.trim().toLowerCase();
    cards.forEach(c => {
      const okFilter = filter === 'all' || c.dataset.type === filter;
      const okSearch = !q || c.textContent.toLowerCase().includes(q);
      c.style.display = okFilter && okSearch ? '' : 'none';
    });
  }

  pills.forEach(p => p.addEventListener('click', () => {
    pills.forEach(x => x.classList.remove('active'));
    p.classList.add('active');
    filter = p.dataset.filter;
    applyFilters();
  }));
  searchInput.addEventListener('input', applyFilters);

  // Start route toggle
  const start = document.getElementById('startRoute');
  const state = document.querySelector('.hero .state span:last-child');
  start.addEventListener('click', () => {
    const started = start.dataset.started === '1';
    start.dataset.started = started ? '0' : '1';
    start.textContent = started ? 'Start route' : 'Route in progress';
    state.textContent = started ? '● Not started' : '● In progress';
  });
})();