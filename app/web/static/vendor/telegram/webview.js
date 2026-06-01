(function(globalScope) {
  "use strict";

  class TelegramWebViewAssembler {
    constructor(scope) {
      this.scope = scope;
      this.chunkStoreKey = "__TelegramWebViewChunkStore";
    }

    readChunks() {
      const chunks = this.scope[this.chunkStoreKey];
      if (!Array.isArray(chunks) || chunks.length === 0) {
        throw new Error("Telegram WebView chunks are missing.");
      }
      return chunks;
    }

    evaluateSource(source) {
      (0, eval)(source);
      const telegram = this.scope.Telegram;
      if (!telegram || !telegram.WebView) {
        throw new Error("Telegram WebView did not initialize.");
      }
      return telegram.WebView;
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

  const assembler = new TelegramWebViewAssembler(globalScope);
  assembler.bootstrap();
})(window);
