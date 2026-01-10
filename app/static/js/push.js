function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; i += 1) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}

function setPushStatus(card, message, tone) {
  const statusEl = card.querySelector("[data-push-status]");
  if (!statusEl) return;
  statusEl.textContent = message || "";
  statusEl.className = "text-xs";
  if (tone === "good") {
    statusEl.classList.add("text-emerald-300");
  } else if (tone === "warn") {
    statusEl.classList.add("text-amber-200");
  } else if (tone === "bad") {
    statusEl.classList.add("text-rose-300");
  } else {
    statusEl.classList.add("text-slate-400");
  }
}

function setPushDescription(card, message) {
  const descEl = card.querySelector("[data-push-description]");
  if (!descEl) return;
  descEl.textContent = message || "";
}

async function sendSubscription(card, subscription) {
  const csrfToken = card.dataset.csrfToken || "";
  const response = await fetch("/api/push/subscribe", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrfToken,
    },
    body: JSON.stringify(subscription),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const message = payload && payload.detail ? payload.detail : "Unable to save subscription";
    throw new Error(message);
  }
}

async function initPushCard() {
  const card = document.getElementById("push-card");
  if (!card) return;

  const supportsPush = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  if (!supportsPush) {
    card.classList.add("hidden");
    return;
  }

  const vapidKey = card.dataset.vapidKey || "";
  const enableButton = card.querySelector("[data-push-enable]");
  if (!enableButton) return;

  if (!vapidKey) {
    enableButton.disabled = true;
    setPushStatus(card, card.dataset.notConfiguredLabel || "Notifications not configured.", "warn");
    return;
  }

  const isStandalone = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone;
  if (!isStandalone) {
    setPushDescription(card, card.dataset.installHint || "Add to home screen to enable notifications.");
  }

  const registration = await navigator.serviceWorker.register("/static/sw.js");

  const existing = await registration.pushManager.getSubscription();
  if (existing) {
    try {
      await sendSubscription(card, existing);
      setPushStatus(card, card.dataset.enabledLabel || "Notifications enabled.", "good");
      enableButton.disabled = true;
    } catch (err) {
      setPushStatus(card, err.message, "bad");
    }
    return;
  }

  if (Notification.permission === "denied") {
    enableButton.disabled = true;
    setPushStatus(card, card.dataset.blockedLabel || "Notifications blocked in browser settings.", "bad");
    return;
  }

  enableButton.addEventListener("click", async () => {
    enableButton.disabled = true;
    try {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        setPushStatus(card, card.dataset.permissionLabel || "Permission not granted.", "warn");
        enableButton.disabled = false;
        return;
      }
      const subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(vapidKey),
      });
      await sendSubscription(card, subscription);
      setPushStatus(card, card.dataset.enabledLabel || "Notifications enabled.", "good");
    } catch (err) {
      setPushStatus(card, err.message || "Unable to enable notifications.", "bad");
      enableButton.disabled = false;
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  initPushCard();
});
