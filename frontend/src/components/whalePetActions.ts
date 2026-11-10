export const petActions = [
  { id: "snack", label: "吃白饭", durationMs: 10000 },
  { id: "dance", label: "摇摆舞", durationMs: 10000 },
  { id: "play", label: "玩魔方", durationMs: 10000 },
  { id: "lion", label: "舞狮头", durationMs: 10067 },
  { id: "think", label: "思考冒泡", durationMs: 10000 },
  { id: "reply", label: "挥挥手", durationMs: 10000 },
] as const;

export type PetActionId = typeof petActions[number]["id"];
export interface PetActionRequest { id: PetActionId; sequence: number }
