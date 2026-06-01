var App = window.App || (window.App = {});

class ChartRegistry {
  constructor(chartCtor = window.Chart) {
    this.chartCtor = chartCtor;
    this.instances = new Map();
  }

  render(key, canvas, config) {
    if (!canvas || !this.chartCtor) return null;

    this.destroy(key);
    const instance = new this.chartCtor(canvas, config);
    this.instances.set(key, instance);
    return instance;
  }

  get(key) {
    return this.instances.get(key) || null;
  }

  destroy(key) {
    const instance = this.instances.get(key);
    if (!instance) return;

    instance.destroy();
    this.instances.delete(key);
  }

  destroyAll() {
    for (const instance of this.instances.values()) {
      instance.destroy();
    }
    this.instances.clear();
  }
}

App.adapters = App.adapters || {};
App.adapters.chart = new ChartRegistry();
