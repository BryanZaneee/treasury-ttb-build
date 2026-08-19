/**
 * The signed-in reviewer.
 *
 * PRD §8 has no user accounts — access is a shared token — so this is a mock
 * session standing in until real authentication exists. It is deliberately the
 * only definition: the masthead renders it and every determination is
 * attributed to it, so there is no way for the name shown and the name recorded
 * to disagree, and no field a reviewer can leave blank or fill in with somebody
 * else's name on the one record where attribution matters most.
 */
export const REVIEWER = {
  name: 'J. Park',
  role: 'Compliance Agent',
  initials: 'JP',
} as const
