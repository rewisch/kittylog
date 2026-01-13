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

function setLogStatus(card, message, tone) {
  const statusEl = card.querySelector("[data-log-status]");
  if (!statusEl) return;
  statusEl.textContent = message || "";
  statusEl.className = "text-xs";
  if (tone === "good") {
    statusEl.classList.add("text-emerald-300");
  } else if (tone === "bad") {
    statusEl.classList.add("text-rose-300");
  } else {
    statusEl.classList.add("text-slate-400");
  }
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

async function disableSubscription(card, subscription) {
  const csrfToken = card.dataset.csrfToken || "";
  await fetch("/api/push/unsubscribe", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrfToken,
    },
    body: JSON.stringify({ endpoint: subscription.endpoint }),
  });
  await subscription.unsubscribe();
}

async function updateLogPreference(card, enabled) {
  const csrfToken = card.dataset.csrfToken || "";
  const response = await fetch("/api/push/log-preference", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrfToken,
    },
    body: JSON.stringify({ enabled }),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const message = payload && payload.detail ? payload.detail : card.dataset.errorLabel;
    throw new Error(message || "Unable to update log notifications.");
  }
  return response.json().catch(() => null);
}

async function initPushCard() {
  const card = document.getElementById("push-card");
  if (!card) return;

  const supportsPush = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  const enableButton = card.querySelector("[data-push-enable]");
  const disableButton = card.querySelector("[data-push-disable]");
  if (!enableButton || !disableButton) return;
  if (!supportsPush) {
    enableButton.disabled = true;
    disableButton.disabled = true;
    setPushStatus(card, card.dataset.notSupportedLabel || "Notifications not supported.", "warn");
    return;
  }

  const vapidKey = card.dataset.vapidKey || "";

  if (!vapidKey) {
    enableButton.disabled = true;
    disableButton.disabled = true;
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
      disableButton.disabled = false;
    } catch (err) {
      setPushStatus(card, err.message, "bad");
    }
  } else {
    disableButton.disabled = true;
    if (Notification.permission === "denied") {
      setPushStatus(card, card.dataset.blockedLabel || "Notifications blocked in browser settings.", "bad");
      enableButton.disabled = true;
    } else {
      setPushStatus(card, card.dataset.disabledLabel || "Notifications disabled.", "neutral");
    }
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
      disableButton.disabled = false;
    } catch (err) {
      setPushStatus(card, err.message || "Unable to enable notifications.", "bad");
      enableButton.disabled = false;
    }
  });

  disableButton.addEventListener("click", async () => {
    disableButton.disabled = true;
    try {
      const current = await registration.pushManager.getSubscription();
      if (current) {
        await disableSubscription(card, current);
      }
      setPushStatus(card, card.dataset.disabledLabel || "Notifications disabled.", "neutral");
      enableButton.disabled = false;
    } catch (err) {
      setPushStatus(card, err.message || "Unable to disable notifications.", "bad");
      disableButton.disabled = false;
    }
  });
}

async function initLogNotifyCard() {
  const card = document.getElementById("log-notify-card");
  if (!card) return;
  const toggle = card.querySelector("[data-log-toggle]");
  if (!toggle) return;

  const enabled = card.dataset.enabled === "true";
  toggle.checked = enabled;
  setLogStatus(
    card,
    enabled ? card.dataset.enabledLabel || "Log notifications enabled." : card.dataset.disabledLabel || "Log notifications disabled.",
    enabled ? "good" : "neutral"
  );

  toggle.addEventListener("change", async () => {
    toggle.disabled = true;
    const targetValue = toggle.checked;
    try {
      await updateLogPreference(card, targetValue);
      setLogStatus(
        card,
        targetValue ? card.dataset.enabledLabel || "Log notifications enabled." : card.dataset.disabledLabel || "Log notifications disabled.",
        targetValue ? "good" : "neutral"
      );
    } catch (err) {
      toggle.checked = !targetValue;
      setLogStatus(card, err.message || card.dataset.errorLabel || "Unable to update log notifications.", "bad");
    } finally {
      toggle.disabled = false;
    }
  });
}

document.addEventListener("DOMContentLoaded", () => {
  initPushCard();
  initLogNotifyCard();
});
