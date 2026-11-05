// Inline SVG icons for vehicles, gas and points of interest.

export const PEAK_ICON = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 5.5 10 11l2.9 3.9-1.7 1.3L7 10.5 1 19h22L14 5.5z" fill="currentColor"/></svg>`;
const icon = (d) => `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${d}" fill="currentColor"/></svg>`;
export const PROFILE_ICONS = {
  car: icon("M18.92 6.01C18.72 5.42 18.16 5 17.5 5h-11c-.66 0-1.21.42-1.42 1.01L3 12v8c0 .55.45 1 1 1h1c.55 0 1-.45 1-1v-1h12v1c0 .55.45 1 1 1h1c.55 0 1-.45 1-1v-8l-2.08-5.99zM6.5 16c-.83 0-1.5-.67-1.5-1.5S5.67 13 6.5 13s1.5.67 1.5 1.5S7.33 16 6.5 16zm11 0c-.83 0-1.5-.67-1.5-1.5s.67-1.5 1.5-1.5 1.5.67 1.5 1.5-.67 1.5-1.5 1.5zM5 11l1.5-4.5h11L19 11H5z"),
  dualsport: icon("M19.44 9.03 15.41 5H11v2h3.59l2 2H5c-2.8 0-5 2.2-5 5s2.2 5 5 5c2.46 0 4.45-1.69 4.9-4h1.65l2.77-2.77c-.21.54-.32 1.14-.32 1.77 0 2.8 2.2 5 5 5s5-2.2 5-5c0-2.65-1.97-4.77-4.56-4.97zM7.82 15C7.4 16.15 6.28 17 5 17c-1.63 0-3-1.37-3-3s1.37-3 3-3c1.28 0 2.4.85 2.82 2H5v2h2.82zM19 17c-1.66 0-3-1.34-3-3s1.34-3 3-3 3 1.34 3 3-1.34 3-3 3z"),
};

export const GAS_ICON = `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="m19.77 7.23.01-.01-3.72-3.72L15 4.56l2.11 2.11c-.94.36-1.61 1.26-1.61 2.33a2.5 2.5 0 0 0 2.5 2.5c.36 0 .69-.08 1-.21v7.21c0 .55-.45 1-1 1s-1-.45-1-1V14c0-1.1-.9-2-2-2h-1V5c0-1.1-.9-2-2-2H6c-1.1 0-2 .9-2 2v16h10v-7.5h1.5v5a2.5 2.5 0 0 0 5 0V9c0-.69-.28-1.32-.73-1.77zM12 10H6V5h6v5zm6 0c-.55 0-1-.45-1-1s.45-1 1-1 1 .45 1 1-.45 1-1 1z"/></svg>`;

const iconEO = (d) => `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${d}" fill="currentColor" fill-rule="evenodd"/></svg>`;
const DROP = "M12 2.5c-5 4.4-7.5 8.1-7.5 11.3a7.5 7.5 0 0 0 15 0c0-3.2-2.5-6.9-7.5-11.3z";
const TENT = "M12 3 1.5 21h7.5L12 15.5 15 21h7.5L12 3z";
const BED = "M2 5h2.5v8h17.5v6h-2.5v-2.5h-15V19H2V5zm5.5 2.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5zm3.5.5h7.5a3.5 3.5 0 0 1 3.5 3.5V12H11V8z";
export const POI_ICONS = {
  water: iconEO(DROP),
  spring: iconEO(`${DROP}M8 15.5c1.3 1 2.7 1 4 0s2.7-1 4 0v1.8c-1.3-1-2.7-1-4 0s-2.7 1-4 0z`),
  campground: iconEO(TENT),
  dispersed: iconEO(TENT),
  rv: iconEO("M2 6h14l5 5v6h-1.8a2.7 2.7 0 0 1-5.4 0H8.2a2.7 2.7 0 0 1-5.4 0H2V6zm2 2v4h4V8H4zm6 0v4h4V8h-4zm6 0v4h3.2L16 8.8V8z"),
  cabin: iconEO("M12 2.5 1.5 11.5h3V21h5.5v-6h4v6h5.5v-9.5h3L12 2.5z"),
  trailhead: iconEO("M11 2h2v3h6.5l2.5 2.5-2.5 2.5H13v12h-2V10H4.5L2 7.5 4.5 5H11V2z"),
  staging: PROFILE_ICONS.dualsport,
  hotel: iconEO(BED), motel: iconEO(BED), inn: iconEO(BED), hostel: iconEO(BED),
  rental: iconEO("M12 2.5 1.5 11.5h3V21h5.5v-6h4v6h5.5v-9.5h3L12 2.5z"),
  ghost_town: iconEO("M3 21V10h3V5h12v5h3v11h-7v-5h-4v5H3zM8 8v3h3V8H8zm5 0v3h3V8h-3z"),
  mine: iconEO("M2 21V11a10 10 0 0 1 20 0v10h-5v-9a5 5 0 0 0-10 0v9H2zm8.5 0v-6h3v6h-3z"),
  ruins: iconEO("M3 22v-2.5h18V22H3zm1.5-4V8l3 1.5V18h-3zm5.5 0V4h4v14h-4zm6 0v-6.5l3-2V18h-3z"),
  viewpoint: iconEO("M12 5C6.5 5 2.7 8.6 1 12c1.7 3.4 5.5 7 11 7s9.3-3.6 11-7c-1.7-3.4-5.5-7-11-7zm0 11.5a4.5 4.5 0 1 1 0-9 4.5 4.5 0 0 1 0 9zm0-2.2a2.3 2.3 0 1 0 0-4.6 2.3 2.3 0 0 0 0 4.6z"),
  peak: iconEO("M14 5.5 10 11l2.9 3.9-1.7 1.3L7 10.5 1 19h22L14 5.5z"),
  lookout: iconEO("M12 1.5 18.5 7H16v4h-1.2L17 22h-2.3l-.6-3.2H9.9L9.3 22H7l2.2-11H8V7H5.5L12 1.5zm-1.4 9.5-.4 5.5h3.6l-.4-5.5h-2.8z"),
  hot_spring: iconEO("M2 15.5c0-2.2 4.5-3.5 10-3.5s10 1.3 10 3.5v.5H2zM2 18h20a4 4 0 0 1-4 4H6a4 4 0 0 1-4-4zM7.2 2.5l1.6.8c-1 1.8 1 3-.1 5.5l-1.6-.8c.9-2-1-3.2.1-5.5zm4 0 1.6.8c-1 1.8 1 3-.1 5.5l-1.6-.8c.9-2-1-3.2.1-5.5zm4 0 1.6.8c-1 1.8 1 3-.1 5.5l-1.6-.8c.9-2-1-3.2.1-5.5z"),
  arch: iconEO("M1.5 21V10.5C1.5 6 6.2 3 12 3s10.5 3 10.5 7.5V21h-5.5v-8c0-2.4-2.2-4-5-4s-5 1.6-5 4v8H1.5z"),
  cave: iconEO("M1 21 7.5 7l2.7 3L13.5 4 23 21H1zm8 0h6v-3.5a3 3 0 0 0-6 0V21z"),
  petroglyph: iconEO("M12 2a2.2 2.2 0 1 1 0 4.4A2.2 2.2 0 0 1 12 2zm-1.2 5.5h2.4v3.6l4.2-3 1.3 1.7-5.5 4v2.6l3.4 5.6h-2.6L12 17.6 10 22H7.4l3.4-5.6v-2.6L5.3 9.8l1.3-1.7 4.2 3V7.5z"),
};
