const calendarEl = document.getElementById('calendar');
const monthSelect = document.getElementById('monthSelect');
const propertyFilter = document.getElementById('propertyFilter');
const updatedAtEl = document.getElementById('updatedAt');
const densityToggle = document.getElementById('densityToggle');

const VIEW_DAYS = 365;
const MIN_DATE = makeUTCDate(2026, 0, 1);
const VIEW_SHIFT_DAYS = 30;
const TIMEZONE = 'America/New_York';

let calendarData = null;
let viewStart = new Date();
let pendingScrollToISO = null;
let focusDate = null;

const monthFormatter = new Intl.DateTimeFormat('en-US', {
  timeZone: 'UTC',
  month: 'long',
  year: 'numeric',
});

const weekdayFormatter = new Intl.DateTimeFormat('en-US', {
  timeZone: 'UTC',
  weekday: 'short',
});

const tzDateFormatter = new Intl.DateTimeFormat('en-US', {
  timeZone: TIMEZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
});

const weekdayHeaders = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

function makeUTCDate(year, month, day) {
  return new Date(Date.UTC(year, month, day));
}

function todayInTimeZone() {
  const parts = tzDateFormatter.formatToParts(new Date());
  const values = {};
  parts.forEach((part) => {
    if (part.type !== 'literal') {
      values[part.type] = part.value;
    }
  });
  const year = Number(values.year);
  const month = Number(values.month);
  const day = Number(values.day);
  return makeUTCDate(year, month - 1, day);
}

function addDays(dateObj, days) {
  const next = new Date(dateObj.getTime());
  next.setUTCDate(next.getUTCDate() + days);
  return next;
}

function parseDate(value) {
  const [year, month, day] = value.split('-').map(Number);
  return makeUTCDate(year, month - 1, day);
}

function dateToISO(dateObj) {
  return dateObj.toISOString().slice(0, 10);
}

function diffDays(start, end) {
  return Math.round((end - start) / (24 * 60 * 60 * 1000));
}

function startOfWeek(dateObj) {
  const day = (dateObj.getUTCDay() + 6) % 7;
  return addDays(dateObj, -day);
}

function getSelectedMonthStart() {
  if (monthSelect && monthSelect.value) {
    const [year, month] = monthSelect.value.split('-').map(Number);
    return makeUTCDate(year, month - 1, 1);
  }
  if (focusDate) {
    return makeUTCDate(focusDate.getUTCFullYear(), focusDate.getUTCMonth(), 1);
  }
  return makeUTCDate(viewStart.getUTCFullYear(), viewStart.getUTCMonth(), 1);
}

function halfIndex(dateObj, rangeStart, half) {
  const diffDays = Math.round((dateObj - rangeStart) / (24 * 60 * 60 * 1000));
  return diffDays * 2 + (half === 'pm' ? 2 : 1);
}

function formatMonthLabel(dateObj) {
  return monthFormatter.format(dateObj);
}

function formatRangeLabel(start, endExclusive) {
  const end = addDays(endExclusive, -1);
  const startLabel = formatMonthLabel(start);
  const endLabel = formatMonthLabel(end);
  return startLabel === endLabel ? startLabel : `${startLabel} → ${endLabel}`;
}

function buildMonthOptions() {
  const months = new Set();
  calendarData.properties.forEach((property) => {
    property.events.forEach((event) => {
      const start = parseDate(event.start);
      const end = parseDate(event.end);
      const cursor = makeUTCDate(start.getUTCFullYear(), start.getUTCMonth(), 1);
      const last = makeUTCDate(end.getUTCFullYear(), end.getUTCMonth(), 1);
      while (cursor <= last) {
        months.add(cursor.toISOString().slice(0, 7));
        cursor.setUTCMonth(cursor.getUTCMonth() + 1);
      }
    });
  });

  const sorted = Array.from(months).sort();
  monthSelect.innerHTML = '';
  sorted.forEach((monthStr) => {
    const option = document.createElement('option');
    option.value = monthStr;
    const [year, month] = monthStr.split('-').map(Number);
    option.textContent = formatMonthLabel(makeUTCDate(year, month - 1, 1));
    monthSelect.appendChild(option);
  });
}

function syncMonthSelect(dateObj) {
  if (!monthSelect || !dateObj) return;
  const value = dateObj.toISOString().slice(0, 7);
  if (monthSelect.value !== value) {
    monthSelect.value = value;
  }
}

function buildPropertyFilter() {
  propertyFilter.innerHTML = '';
  const allOption = document.createElement('option');
  allOption.value = 'all';
  allOption.textContent = 'All Properties';
  propertyFilter.appendChild(allOption);

  calendarData.properties.forEach((property) => {
    const option = document.createElement('option');
    option.value = property.name;
    option.textContent = property.name;
    propertyFilter.appendChild(option);
  });
}

function computeEventSpan(event, rangeStart, rangeEndExclusive, reservationCheckouts) {
  const eventStart = parseDate(event.start);
  const eventEnd = parseDate(event.end);

  if (eventEnd <= rangeStart || eventStart >= rangeEndExclusive) {
    return null;
  }

  const displayStart = eventStart < rangeStart ? rangeStart : eventStart;
  const displayEnd = eventEnd > rangeEndExclusive ? rangeEndExclusive : eventEnd;
  const days = Math.round((rangeEndExclusive - rangeStart) / (24 * 60 * 60 * 1000));

  if (event.type === 'closed') {
    const startsOnCheckout = reservationCheckouts.has(event.start);
    const startHalf = halfIndex(displayStart, rangeStart, startsOnCheckout ? 'pm' : 'am');
    const endHalf = eventEnd >= rangeEndExclusive
      ? days * 2 + 1
      : halfIndex(displayEnd, rangeStart, 'am');
    return { startHalf, endHalf };
  }

  const startHalf = eventStart < rangeStart
    ? halfIndex(rangeStart, rangeStart, 'am')
    : halfIndex(displayStart, rangeStart, 'pm');

  const endHalf = eventEnd >= rangeEndExclusive
    ? days * 2 + 1
    : halfIndex(displayEnd, rangeStart, 'am') + 1;

  return { startHalf, endHalf };
}

function applyDensity(mode) {
  if (!densityToggle) return;
  const stored = mode || localStorage.getItem('calendarDensity') || 'comfortable';
  const nextMode = stored === 'compact' ? 'compact' : 'comfortable';
  localStorage.setItem('calendarDensity', nextMode);
  if (nextMode === 'compact') {
    calendarEl.classList.add('compact');
    densityToggle.title = 'Compact';
    densityToggle.setAttribute('aria-pressed', 'true');
  } else {
    calendarEl.classList.remove('compact');
    densityToggle.title = 'Comfortable';
    densityToggle.setAttribute('aria-pressed', 'false');
  }
}

function setViewStart(dateObj, scrollToISO, focusOverride) {
  viewStart = makeUTCDate(dateObj.getUTCFullYear(), dateObj.getUTCMonth(), dateObj.getUTCDate());
  focusDate = focusOverride || addDays(viewStart, 7);
  syncMonthSelect(focusDate);
  if (scrollToISO) {
    pendingScrollToISO = scrollToISO;
  }
  renderCalendar();
}

function setFocusDate(dateObj) {
  const clamped = dateObj < MIN_DATE ? MIN_DATE : dateObj;
  viewStart = MIN_DATE;
  focusDate = clamped;
  syncMonthSelect(focusDate);
  pendingScrollToISO = dateToISO(clamped);
  renderCalendar();
}

function renderCalendar() {
  if (!calendarData) return;

  const filterValue = propertyFilter.value;
  calendarEl.classList.toggle('single', filterValue !== 'all');

  if (filterValue !== 'all') {
    const property = calendarData.properties.find((prop) => prop.name === filterValue);
    renderSingleProperty(property);
    return;
  }

  let rangeStart = viewStart;
  const daysFromMin = diffDays(MIN_DATE, viewStart);
  if (daysFromMin >= 0 && daysFromMin < VIEW_DAYS) {
    rangeStart = MIN_DATE;
  }
  const rangeEndExclusive = addDays(rangeStart, VIEW_DAYS);
  const days = VIEW_DAYS;

  calendarEl.style.setProperty('--days', days);
  calendarEl.style.setProperty('--half-days', days * 2);

  const labelDate = getSelectedMonthStart() || focusDate || rangeStart;

  const header = document.createElement('div');
  header.className = 'calendar-header';

  const todayUTC = todayInTimeZone();

  for (let i = 0; i < days; i += 1) {
    const dayCell = document.createElement('div');
    const dateObj = addDays(rangeStart, i);
    dayCell.className = 'day-cell';
    dayCell.innerHTML = `${dateObj.getUTCDate()}<br><span>${weekdayFormatter.format(dateObj)}</span>`;
    dayCell.style.gridColumn = 'span 2';
    dayCell.dataset.date = dateToISO(dateObj);
    const weekday = dateObj.getUTCDay();
    if (weekday === 0 || weekday === 6) {
      dayCell.classList.add('weekend-cell');
    }
    if (dateToISO(dateObj) === dateToISO(todayUTC)) {
      dayCell.classList.add('today-cell');
    }
    header.appendChild(dayCell);
  }

  const body = document.createElement('div');
  body.className = 'calendar-body';

  const properties = calendarData.properties.filter((property) => {
    return filterValue === 'all' || property.name === filterValue;
  });

  const leftCol = document.createElement('div');
  leftCol.className = 'calendar-left';
  const leftHeader = document.createElement('div');
  leftHeader.className = 'calendar-left-header';
  leftHeader.textContent = formatMonthLabel(labelDate);
  leftCol.appendChild(leftHeader);

  const leftBody = document.createElement('div');
  leftBody.className = 'calendar-left-body';

  properties.forEach((property) => {
    const leftRow = document.createElement('div');
    leftRow.className = 'calendar-left-row';
    leftRow.textContent = property.name;
    leftBody.appendChild(leftRow);

    const row = document.createElement('div');
    row.className = 'property-row';

    const grid = document.createElement('div');
    grid.className = 'property-grid';

    const availabilityLayer = document.createElement('div');
    availabilityLayer.className = 'availability-layer';
    availabilityLayer.style.gridTemplateColumns = `repeat(${days * 2}, var(--cell-width))`;
    grid.appendChild(availabilityLayer);

    const reservationStarts = new Set();
    const reservationEnds = new Set();
    const reservationCheckouts = new Set();

    property.events.forEach((event) => {
      if (event.type === 'closed') return;
      reservationStarts.add(event.start);
      reservationEnds.add(event.end);
      reservationCheckouts.add(event.end);
    });

    const quickTurns = new Set(
      [...reservationStarts].filter((dateStr) => reservationEnds.has(dateStr))
    );

    const occupied = new Set();

    property.events.forEach((event) => {
      const span = computeEventSpan(event, rangeStart, rangeEndExclusive, reservationCheckouts);
      if (!span) return;

      const { startHalf, endHalf } = span;
      if (endHalf <= startHalf) return;

      for (let half = startHalf; half < endHalf; half += 1) {
        occupied.add(half);
      }

      const pill = document.createElement('div');
      pill.className = `event-pill ${event.type === 'closed' ? 'event-closed' : 'event-reservation'}`;
      pill.style.gridColumn = `${startHalf} / ${endHalf}`;
      pill.textContent = '';
      pill.title = `${event.summary || 'Reservation'} (${event.start} → ${event.end})`;
      grid.appendChild(pill);
    });

    for (let day = 0; day < days; day += 1) {
      const cell = document.createElement('div');
      cell.className = 'availability-cell';
      const firstHalf = day * 2 + 1;
      const secondHalf = firstHalf + 1;
      if (occupied.has(firstHalf) || occupied.has(secondHalf)) {
        cell.classList.add('occupied');
      }
      const cellDate = addDays(rangeStart, day);
      const cellISO = dateToISO(cellDate);
      if (quickTurns.has(cellISO)) {
        cell.classList.add('quick-turn');
      }
      const weekday = cellDate.getUTCDay();
      if (weekday === 0 || weekday === 6) {
        cell.classList.add('weekend-cell');
      }
      cell.style.gridColumn = `${firstHalf} / ${firstHalf + 2}`;
      availabilityLayer.appendChild(cell);
    }

    row.appendChild(grid);
    body.appendChild(row);
  });

  leftCol.appendChild(leftBody);

  calendarEl.innerHTML = '';
  const shell = document.createElement('div');
  shell.className = 'calendar-shell';

  const scroll = document.createElement('div');
  scroll.className = 'calendar-scroll';
  scroll.appendChild(header);
  scroll.appendChild(body);

  shell.appendChild(leftCol);
  shell.appendChild(scroll);
  calendarEl.appendChild(shell);

  if (pendingScrollToISO) {
    const target = pendingScrollToISO;
    pendingScrollToISO = null;
    requestAnimationFrame(() => {
      const targetCell = scroll.querySelector(`.day-cell[data-date="${target}"]`);
      if (targetCell) {
        targetCell.scrollIntoView({ inline: 'center', block: 'nearest', behavior: 'smooth' });
      }
    });
  }
}

function shiftView(days) {
  if (propertyFilter.value !== 'all') {
    const current = getSelectedMonthStart();
    const delta = days > 0 ? 1 : -1;
    const next = makeUTCDate(current.getUTCFullYear(), current.getUTCMonth() + delta, 1);
    setViewStart(next, dateToISO(next), next);
    return;
  }
  const currentFocus = focusDate || viewStart;
  const nextFocus = addDays(currentFocus, days);
  setFocusDate(nextFocus);
}

function hookControls() {
  document.getElementById('prev').addEventListener('click', () => shiftView(-VIEW_SHIFT_DAYS));
  document.getElementById('next').addEventListener('click', () => shiftView(VIEW_SHIFT_DAYS));
  document.getElementById('today').addEventListener('click', () => {
    const todayUTC = todayInTimeZone();
    if (propertyFilter.value === 'all') {
      setFocusDate(todayUTC);
    } else {
      setViewStart(addDays(todayUTC, -7), dateToISO(todayUTC), todayUTC);
    }
  });

  if (densityToggle) {
    densityToggle.addEventListener('click', () => {
      const current = localStorage.getItem('calendarDensity') || 'comfortable';
      const next = current === 'compact' ? 'comfortable' : 'compact';
      applyDensity(next);
    });
  }

  monthSelect.addEventListener('change', () => {
    const [year, month] = monthSelect.value.split('-').map(Number);
    const target = makeUTCDate(year, month - 1, 1);
    if (propertyFilter.value === 'all') {
      setFocusDate(target);
    } else {
      setViewStart(target, dateToISO(target), target);
    }
    if (propertyFilter.value !== 'all') {
      const prev = makeUTCDate(year, month - 2, 1);
      const next = makeUTCDate(year, month, 1);
      monthSelect.dataset.prev = `${prev.getUTCFullYear()}-${String(prev.getUTCMonth() + 1).padStart(2, '0')}`;
      monthSelect.dataset.next = `${next.getUTCFullYear()}-${String(next.getUTCMonth() + 1).padStart(2, '0')}`;
    }
  });

  propertyFilter.addEventListener('change', () => {
    renderCalendar();
  });
}

function showError(message) {
  calendarEl.innerHTML = `<div class="error">${message}</div>`;
}

function renderSingleProperty(property) {
  calendarEl.innerHTML = '';
  if (!property) {
    showError('No property selected.');
    return;
  }

  const monthStart = getSelectedMonthStart();
  const monthEndExclusive = makeUTCDate(monthStart.getUTCFullYear(), monthStart.getUTCMonth() + 1, 1);
  const gridStart = startOfWeek(monthStart);
  const gridEndExclusive = addDays(startOfWeek(addDays(monthEndExclusive, -1)), 7);
  const totalDays = diffDays(gridStart, gridEndExclusive);
  const weeks = Math.ceil(totalDays / 7);

  const wrapper = document.createElement('div');
  wrapper.className = 'single-calendar';
  wrapper.addEventListener('wheel', (event) => {
    let delta = event.deltaX;
    if (Math.abs(event.deltaX) <= Math.abs(event.deltaY) && event.shiftKey) {
      delta = event.deltaY;
    }
    if (!delta) return;
    event.preventDefault();
    if (delta > 0) {
      shiftView(1);
    } else if (delta < 0) {
      shiftView(-1);
    }
  }, { passive: false });

  const header = document.createElement('div');
  header.className = 'single-header';
  header.innerHTML = `
    <div class="single-month">${formatMonthLabel(monthStart)}</div>
    <div class="single-property">${property.name}</div>
  `;
  wrapper.appendChild(header);

  const weekdayRow = document.createElement('div');
  weekdayRow.className = 'weekday-row';
  weekdayHeaders.forEach((label) => {
    const cell = document.createElement('div');
    cell.className = 'weekday-cell';
    cell.textContent = label;
    weekdayRow.appendChild(cell);
  });
  wrapper.appendChild(weekdayRow);

  const reservationStarts = new Map();
  const reservationEnds = new Map();
  const events = property.events.map((event) => ({
    ...event,
    startDate: parseDate(event.start),
    endDate: parseDate(event.end),
  })).filter((event) => event.startDate && event.endDate);

  events.forEach((event) => {
    if (event.type !== 'closed') {
      if (!reservationStarts.has(event.start)) reservationStarts.set(event.start, new Set());
      if (!reservationEnds.has(event.end)) reservationEnds.set(event.end, new Set());
      reservationStarts.get(event.start).add(event.uid);
      reservationEnds.get(event.end).add(event.uid);
    }
  });
  const quickTurns = new Set();
  reservationStarts.forEach((startIds, dateStr) => {
    const endIds = reservationEnds.get(dateStr);
    if (!endIds) return;
    const hasDifferent = [...startIds].some((id) => !endIds.has(id));
    if (hasDifferent) quickTurns.add(dateStr);
  });
  const reservationCheckouts = new Set([...reservationEnds.keys()]);

  const occupied = new Set();
  events.forEach((event) => {
    if (event.endDate <= gridStart || event.startDate >= gridEndExclusive) return;
    const start = event.startDate < gridStart ? gridStart : event.startDate;
    const end = event.endDate > gridEndExclusive ? gridEndExclusive : event.endDate;
    for (let day = 0; day < diffDays(start, end); day += 1) {
      occupied.add(dateToISO(addDays(start, day)));
    }
  });

  const todayUTC = todayInTimeZone();

  for (let w = 0; w < weeks; w += 1) {
    const weekStart = addDays(gridStart, w * 7);
    const weekRow = document.createElement('div');
    weekRow.className = 'week-row';

    const weekCells = document.createElement('div');
    weekCells.className = 'week-cells';

    for (let d = 0; d < 7; d += 1) {
      const dateObj = addDays(weekStart, d);
      const cell = document.createElement('div');
      cell.className = 'month-cell';
      cell.dataset.date = dateToISO(dateObj);
      if (dateObj.getUTCMonth() !== monthStart.getUTCMonth()) {
        cell.classList.add('outside');
      }
      if (dateToISO(dateObj) === dateToISO(todayUTC)) {
        cell.classList.add('today');
      }
      if (occupied.has(dateToISO(dateObj))) {
        cell.classList.add('occupied');
      }
      if (quickTurns.has(dateToISO(dateObj))) {
        cell.classList.add('quick-turn');
      }
      const weekday = dateObj.getUTCDay();
      if (weekday === 0 || weekday === 6) {
        cell.classList.add('weekend');
      }
      const label = document.createElement('span');
      label.className = 'day-number';
      label.textContent = dateObj.getUTCDate();
      cell.appendChild(label);
      weekCells.appendChild(cell);
    }

    const weekEvents = document.createElement('div');
    weekEvents.className = 'week-events';

    events.forEach((event) => {
      if (event.endDate <= weekStart || event.startDate >= addDays(weekStart, 7)) return;
      const rangeStart = weekStart;
      const rangeEndExclusive = addDays(weekStart, 7);
      const displayStart = event.startDate < rangeStart ? rangeStart : event.startDate;
      const displayEnd = event.endDate > rangeEndExclusive ? rangeEndExclusive : event.endDate;
      if (displayEnd <= displayStart) return;

      let colStart;
      let colEnd;
      if (event.type === 'closed') {
        const startsOnCheckout = reservationCheckouts.has(event.start);
        colStart = halfIndex(displayStart, rangeStart, startsOnCheckout ? 'pm' : 'am');
        colEnd = event.endDate >= rangeEndExclusive
          ? 7 * 2 + 1
          : halfIndex(displayEnd, rangeStart, 'am');
      } else {
        colStart = event.startDate < rangeStart
          ? halfIndex(rangeStart, rangeStart, 'am')
          : halfIndex(displayStart, rangeStart, 'pm');
        colEnd = event.endDate >= rangeEndExclusive
          ? 7 * 2 + 1
          : halfIndex(displayEnd, rangeStart, 'am') + 1;
      }
      if (colEnd <= colStart) return;
      const pill = document.createElement('div');
      pill.className = `event-pill ${event.type === 'closed' ? 'event-closed' : 'event-reservation'}`;
      pill.style.gridColumn = `${colStart} / ${colEnd}`;
      pill.title = `${event.summary || 'Reservation'} (${event.start} → ${event.end})`;
      weekEvents.appendChild(pill);
    });

    weekRow.appendChild(weekCells);
    weekRow.appendChild(weekEvents);
    wrapper.appendChild(weekRow);
  }

  calendarEl.appendChild(wrapper);
}

async function loadData() {
  try {
    if (window.__CALENDAR_DATA__) {
      calendarData = window.__CALENDAR_DATA__;
    } else {
      const response = await fetch('./calendar_data.json');
      if (!response.ok) {
        throw new Error(`Failed to load data: ${response.status}`);
      }
      calendarData = await response.json();
    }

    if (!calendarData || !calendarData.properties) {
      throw new Error('Calendar data missing or invalid.');
    }

    if (updatedAtEl && calendarData.generated_at) {
      const stamp = new Date(calendarData.generated_at);
      const formatted = stamp.toLocaleString('en-US', {
        timeZone: TIMEZONE,
        year: 'numeric',
        month: 'numeric',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
      });
      updatedAtEl.textContent = `Updated ${formatted}`;
    }

    buildMonthOptions();
    buildPropertyFilter();
    applyDensity();
    hookControls();

    const start = makeUTCDate(2026, 0, 1);
    viewStart = start;
    focusDate = addDays(start, 7);
    syncMonthSelect(focusDate);
    renderCalendar();
  } catch (err) {
    console.error(err);
    showError('No calendar data loaded. Re-run build_calendar_data.py and refresh.');
  }
}

loadData();
