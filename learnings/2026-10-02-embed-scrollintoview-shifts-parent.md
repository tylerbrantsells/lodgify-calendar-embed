# scrollIntoView inside an iframe scrolls the host page

**Problem:** On the Notion turnover dashboard, using the calendar embed and scrolling back up left the page shifted left. The title lost its first letter. The embed's own document was not wider than the iframe.

**Dead ends:** Clipping the day grid was not the leak. `.calendar-scroll` already held the 365-day grid, and the iframe document's scroll width matched its width. The host page was wider because of the Notion database, so a small horizontal scroll stuck.

**What worked:** Stop calling `scrollIntoView`. Set `scrollLeft` on `.calendar-scroll` only. That centres today in the timeline and leaves the parent `scrollLeft` at 0. `overscroll-behavior-x: contain` stops a sideways flick from chaining out of the timeline.

**The rule:** In an embedded page, never call `scrollIntoView` on a wide timeline. It scrolls every ancestor, including the host page. Move `scrollLeft` on the one overflow element that should move.

**Applies when:** An iframe calendar, table, or chart centres a cell on load, and the host page is wider than the window.
