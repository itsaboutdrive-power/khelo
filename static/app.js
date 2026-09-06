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
  window.location.href = user.profile_required ? "/static/profile.html" : (user.role === "court_manager" ? "/venues/new" : "/");
};

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
  try {
    const user = await request("/api/auth/signup", {
      method: "POST",
      body: JSON.stringify({
        email: document.getElementById("signup-email").value,
        password: document.getElementById("signup-password").value,
        role: document.getElementById("signup-role").value,
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
    window.location.href = profile.role === "court_manager" ? "/venues/new" : "/";
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