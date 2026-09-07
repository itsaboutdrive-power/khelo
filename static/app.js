const savedUser = () => JSON.parse(localStorage.getItem("kheloUser") || "null");
const showMessage = (message, isError = true) => {
  const element = document.getElementById("form-message");
  if (element) {
    element.textContent = message;
    element.classList.toggle("error", isError);
  }
};

const request = async (url, options) => {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.detail || "Something went wrong.");
  return body;
};

const continueAfterAuth = (user) => {
  localStorage.setItem("kheloUser", JSON.stringify(user));
  window.location.href = user.profile_required ? "/static/profile.html" : (user.role === "court_manager" ? "/venues/new" : "/static/player-venues.html");
};

const selectedRole = () => document.querySelector('input[name="role"]:checked')?.value || "player";

document.getElementById("show-login")?.addEventListener("click", () => {
  document.getElementById("login-form").classList.remove("hidden-form");
  document.getElementById("email").focus();
});

document.getElementById("google-signin")?.addEventListener("click", () => {
  showMessage("Google sign-in needs OAuth credentials before it can be used.");
});

document.getElementById("signup-option")?.addEventListener("click", () => {
  sessionStorage.setItem("kheloSignupRole", selectedRole());
});

document.getElementById("login-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const user = await request("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({
        email: document.getElementById("email").value,
        password: document.getElementById("password").value,
      }),
    });
    continueAfterAuth(user);
  } catch (error) { showMessage(error.message); }
});

document.getElementById("signup-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (document.getElementById("signup-password").value !== document.getElementById("confirm-password").value) {
    showMessage("Passwords do not match.");
    return;
  }
  try {
    const user = await request("/api/auth/signup", {
      method: "POST",
      body: JSON.stringify({
        email: document.getElementById("signup-email").value,
        password: document.getElementById("signup-password").value,
        role: sessionStorage.getItem("kheloSignupRole") || "player",
        full_name: document.getElementById("full-name").value,
        profile_picture_url: document.getElementById("profile-picture").value || null,
      }),
    });
    continueAfterAuth(user);
  } catch (error) { showMessage(error.message); }
});

document.getElementById("profile-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const user = savedUser();
  if (!user) { window.location.href = "/"; return; }
  try {
    const profile = await request(`/api/users/${user.user_id}/profile`, {
      method: "PUT",
      body: JSON.stringify({
        full_name: document.getElementById("full-name").value,
        profile_picture_url: document.getElementById("profile-picture").value || null,
      }),
    });
    localStorage.setItem("kheloUser", JSON.stringify({ ...user, ...profile }));
    window.location.href = profile.role === "court_manager" ? "/venues/new" : "/static/player-venues.html";
  } catch (error) { showMessage(error.message); }
});

const sportSelect = document.getElementById("sport");
if (sportSelect) {
  request("/api/sports", { method: "GET" })
    .then((sports) => {
      sportSelect.innerHTML = '<option value="">Choose a sport</option>';
      sports.forEach((sport) => {
        sportSelect.add(new Option(sport.name, sport.id));
      });
    })
    .catch((error) => { sportSelect.innerHTML = "<option>Sports unavailable</option>"; showMessage(error.message); });
}

document.getElementById("venue-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const user = savedUser();
  if (!user || user.role !== "court_manager") { showMessage("Sign in as a court manager first."); return; }
  try {
    const result = await request("/api/venues", {
      method: "POST",
      body: JSON.stringify({
        manager_id: user.user_id,
        name: document.getElementById("venue-name").value,
        sport_id: Number(document.getElementById("sport").value),
        address: document.getElementById("address").value,
        google_maps_url: document.getElementById("maps-url").value,
        slot_duration_minutes: Number(document.getElementById("duration").value),
        opens_at: document.getElementById("opens-at").value,
        closes_at: document.getElementById("closes-at").value,
        booking_price_cents: Number(document.getElementById("price").value) * 100,
        photo_urls: document.getElementById("photos").value.split(",").map((url) => url.trim()).filter(Boolean),
      }),
    });
    showMessage(`Venue "${result.name}" registered successfully.`, false);
    event.target.reset();
  } catch (error) { showMessage(error.message); }
});

const venueResults = document.getElementById("venue-results");
const filterSports = document.getElementById("sport-filters");
let playerLocation;

const loadPlayerVenues = async () => {
  const user = savedUser();
  if (!user || user.role !== "player") { window.location.href = "/"; return; }
  if (!playerLocation) { showMessage("Allow location access to find courts within 10 km."); return; }
  const parameters = new URLSearchParams({
    player_id: user.user_id,
    latitude: playerLocation.latitude,
    longitude: playerLocation.longitude,
    max_distance_km: "10",
  });
  [...filterSports.selectedOptions].forEach((sport) => parameters.append("sport_ids", sport.value));
  const sort = document.getElementById("price-sort").value;
  if (sort) parameters.set("sort_by_price", sort);
  try {
    const result = await request(`/api/venues/discover?${parameters}`, { method: "GET" });
    venueResults.innerHTML = result.venues.length
      ? result.venues.map((venue) => `<article class="venue-result"><div><p class="form-kicker">${venue.sport}</p><h3>${venue.name}</h3><p>${venue.address}</p></div><div class="venue-meta"><strong>${(venue.booking_price_cents / 100).toFixed(0)} ${venue.currency}</strong><span>${(venue.distance_meters / 1000).toFixed(1)} km away</span><a href="${venue.google_maps_url}" target="_blank" rel="noreferrer">Map</a></div></article>`).join("")
      : "<p>No courts are currently available within 10 km.</p>";
    showMessage("", false);
  } catch (error) { showMessage(error.message); }
};

if (venueResults) {
  request("/api/sports", { method: "GET" })
    .then((sports) => sports.forEach((sport) => filterSports.add(new Option(sport.name, sport.id))))
    .catch((error) => showMessage(error.message));
  navigator.geolocation.getCurrentPosition(
    (position) => {
      playerLocation = position.coords;
      loadPlayerVenues();
      window.setInterval(loadPlayerVenues, 10000);
    },
    () => showMessage("Location access is required to find nearby courts."),
    { enableHighAccuracy: true, maximumAge: 30000, timeout: 10000 },
  );
}