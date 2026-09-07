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
const venueDetail = document.getElementById("venue-detail");
let playerLocation;
let selectedVenue;

const escapeHtml = (value) => String(value).replace(/[&<>'"]/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
}[character]));

const renderAvailability = (availability) => {
  const slots = document.getElementById("venue-slots");
  document.getElementById("availability-message").textContent = `${availability.date} · green is available, black is booked`;
  slots.innerHTML = availability.slots.length
    ? availability.slots.map((slot) => `<button class="slot ${slot.status}" type="button" ${slot.status === "booked" ? "disabled" : ""} title="${slot.status === "booked" ? "Booked" : "Available"}">${new Date(slot.starts_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })} - ${new Date(slot.ends_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</button>`).join("")
    : "<p>No slots are available today.</p>";
};

const renderRatings = (result) => {
  const ratings = document.getElementById("venue-ratings");
  document.getElementById("ratings-message").textContent = result.ratings.length ? "Sorted by community activity" : "Be the first to leave a rating.";
  ratings.innerHTML = result.ratings.map((rating) => `<article class="rating-card">
    <div class="rating-card-heading"><strong>${"★".repeat(rating.rating)}${"☆".repeat(5 - rating.rating)}</strong><time>${new Date(rating.created_at).toLocaleDateString()}</time></div>
    <p>${escapeHtml(rating.rating_text)}</p>
    <div class="rating-actions"><button type="button" data-rating-action="like" data-rating-id="${rating.rating_id}">Like <span>${rating.likes}</span></button><button type="button" data-rating-action="dislike" data-rating-id="${rating.rating_id}">Dislike <span>${rating.dislikes}</span></button><button type="button" data-reply-toggle="${rating.rating_id}">Reply</button></div>
    <div class="rating-replies">${(rating.replies || []).map((reply) => `<p><strong>Reply:</strong> ${escapeHtml(reply.rating_text)}</p>`).join("")}</div>
    <form class="reply-form hidden-form" data-reply-form="${rating.rating_id}"><input name="reply_text" maxlength="2000" placeholder="Write a reply" required /><button class="reply-submit" type="submit">Send</button></form>
  </article>`).join("") || "<p>No ratings yet.</p>";
};

const loadVenueDetail = async (venue) => {
  const user = savedUser();
  selectedVenue = venue;
  venueDetail.classList.remove("hidden");
  document.getElementById("selected-venue-name").textContent = venue.name;
  document.getElementById("selected-venue-address").textContent = venue.address;
  document.getElementById("selected-venue-map").href = venue.google_maps_url;
  document.getElementById("venue-slots").innerHTML = "<p>Checking availability...</p>";
  document.getElementById("venue-ratings").innerHTML = "<p>Loading ratings...</p>";
  venueDetail.scrollIntoView({ behavior: "smooth", block: "start" });
  try {
    const [availability, ratings] = await Promise.all([
      request(`/api/venues/${venue.venue_id}/availability?user_id=${user.user_id}`, { method: "GET" }),
      request(`/api/venues/${venue.venue_id}/ratings?user_id=${user.user_id}`, { method: "GET" }),
    ]);
    if (selectedVenue.venue_id !== venue.venue_id) return;
    renderAvailability(availability);
    renderRatings(ratings);
  } catch (error) {
    showMessage(error.message);
  }
};

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
      ? result.venues.map((venue) => `<article class="venue-result" tabindex="0" role="button" data-venue-id="${venue.venue_id}"><div><p class="form-kicker">${venue.sport}</p><h3>${escapeHtml(venue.name)}</h3><p>${escapeHtml(venue.address)}</p></div><div class="venue-meta"><strong>${(venue.booking_price_cents / 100).toFixed(0)} ${venue.currency}</strong><span>${(venue.distance_meters / 1000).toFixed(1)} km away</span><a href="${venue.google_maps_url}" target="_blank" rel="noreferrer">Map</a></div></article>`).join("")
      : "<p>No courts are currently available within 10 km.</p>";
    venueResults.querySelectorAll("[data-venue-id]").forEach((card) => {
      const venue = result.venues.find((item) => item.venue_id === card.dataset.venueId);
      card.addEventListener("click", (event) => { if (event.target.tagName !== "A") loadVenueDetail(venue); });
      card.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); loadVenueDetail(venue); } });
    });
    showMessage("", false);
  } catch (error) { showMessage(error.message); }
};

venueDetail?.addEventListener("click", async (event) => {
  const actionButton = event.target.closest("[data-rating-action]");
  const replyToggle = event.target.closest("[data-reply-toggle]");
  if (replyToggle) document.querySelector(`[data-reply-form="${replyToggle.dataset.replyToggle}"]`).classList.toggle("hidden-form");
  if (!actionButton || !selectedVenue) return;
  try {
    await request(`/api/ratings/${actionButton.dataset.ratingId}/${actionButton.dataset.ratingAction}?user_id=${savedUser().user_id}`, { method: "POST" });
    const ratings = await request(`/api/venues/${selectedVenue.venue_id}/ratings?user_id=${savedUser().user_id}`, { method: "GET" });
    renderRatings(ratings);
  } catch (error) { showMessage(error.message); }
});

venueDetail?.addEventListener("submit", async (event) => {
  const form = event.target.closest("[data-reply-form]");
  if (!form || !selectedVenue) return;
  event.preventDefault();
  try {
    await request(`/api/ratings/${form.dataset.replyForm}/replies`, { method: "POST", body: JSON.stringify({ user_id: savedUser().user_id, reply_text: form.reply_text.value }) });
    const ratings = await request(`/api/venues/${selectedVenue.venue_id}/ratings?user_id=${savedUser().user_id}`, { method: "GET" });
    renderRatings(ratings);
  } catch (error) { showMessage(error.message); }
});

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