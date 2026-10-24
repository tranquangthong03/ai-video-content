import type { Theme } from "../generated";

export type MotionPreset = {
  spring: { damping: number; stiffness: number; mass: number };
  transitionFrames: number; // fade-in length at the start of each scene
  clickZoom: number; // scale reached when zooming to a click point
  kenBurns: number; // extra scale a still image drifts through over a scene
};

export const MOTION: Record<Theme["motion_preset"], MotionPreset> = {
  energetic: {
    spring: { damping: 9, stiffness: 160, mass: 0.7 },
    transitionFrames: 6,
    clickZoom: 1.9,
    kenBurns: 0.14,
  },
  calm: {
    spring: { damping: 22, stiffness: 70, mass: 1 },
    transitionFrames: 14,
    clickZoom: 1.5,
    kenBurns: 0.07,
  },
};
