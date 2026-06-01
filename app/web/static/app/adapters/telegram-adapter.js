var App = window.App || (window.App = {});

class TelegramWebAppAdapter {
  constructor(telegramGlobal = window.Telegram) {
    this.telegramGlobal = telegramGlobal;
  }

  get webApp() {
    return (this.telegramGlobal && this.telegramGlobal.WebApp) || null;
  }

  init() {
    const webApp = this.webApp;
    if (!webApp) return null;

    webApp.ready();
    webApp.expand();

    return {
      webApp,
      initData: webApp.initData || "",
    };
  }

  requestFullscreen() {
    const webApp = this.webApp;
    if (!webApp || typeof webApp.requestFullscreen !== "function") {
      return false;
    }

    try {
      webApp.requestFullscreen();
      return true;
    } catch (_error) {
      return false;
    }
  }

  exitFullscreen() {
    const webApp = this.webApp;
    if (!webApp || typeof webApp.exitFullscreen !== "function") {
      return false;
    }

    try {
      webApp.exitFullscreen();
      return true;
    } catch (_error) {
      return false;
    }
  }
}

App.adapters = App.adapters || {};
App.adapters.telegram = new TelegramWebAppAdapter();
