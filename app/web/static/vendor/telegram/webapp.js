(function(globalScope) {
  "use strict";

  class TelegramWebAppAssembler {
    constructor(scope) {
      this.scope = scope;
      this.chunkStoreKey = "__TelegramWebAppChunkStore";
    }

    readChunks() {
      const chunks = this.scope[this.chunkStoreKey];
      if (!Array.isArray(chunks) || chunks.length === 0) {
        throw new Error("Telegram WebApp chunks are missing.");
      }
      return chunks;
    }

    evaluateSource(source) {
      (0, eval)(source);
      const telegram = this.scope.Telegram;
      if (!telegram || !telegram.WebApp) {
        throw new Error("Telegram WebApp did not initialize.");
      }
      return telegram.WebApp;
    }

    cleanup() {
      delete this.scope[this.chunkStoreKey];
    }

    bootstrap() {
      const source = this.readChunks().join("");
      try {
        return this.evaluateSource(source);
      } finally {
        this.cleanup();
      }
    }
  }

  const assembler = new TelegramWebAppAssembler(globalScope);
  assembler.bootstrap();
})(window);
