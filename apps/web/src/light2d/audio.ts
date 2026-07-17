export type MouthState = "closed" | "small" | "medium" | "large";

export type MouthThresholds = {
  silence_gate: number;
  small_threshold: number;
  medium_threshold: number;
};

export type EnergyTiming = {
  attack_ms: number;
  release_ms: number;
};

export function computeRms(samples: Float32Array): number {
  if (samples.length === 0) return 0;
  let sumSquares = 0;
  for (const sample of samples) sumSquares += sample * sample;
  return Math.sqrt(sumSquares / samples.length);
}

export function mouthStateForEnergy(energy: number, thresholds: MouthThresholds): MouthState {
  if (energy < thresholds.silence_gate) return "closed";
  if (energy < thresholds.small_threshold) return "small";
  if (energy < thresholds.medium_threshold) return "medium";
  return "large";
}

export function createEnergySmoother(timing: EnergyTiming) {
  let value = 0;
  return {
    update(target: number, deltaMs: number): number {
      const duration = target > value ? timing.attack_ms : timing.release_ms;
      const alpha = 1 - Math.exp(-Math.max(0, deltaMs) / Math.max(1, duration));
      value += (Math.max(0, target) - value) * alpha;
      return value;
    },
    reset(): void {
      value = 0;
    },
  };
}
