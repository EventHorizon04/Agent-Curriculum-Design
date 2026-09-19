/**
 * Whether intake is creating a program or editing the selected one.
 *
 * `/intake` is both screens, so the URL cannot tell them apart, and the id in
 * `useProgram` cannot either: it lives in localStorage and outlives every
 * mount, so a program is always selected and edit mode would always win. The
 * router's location state carries the distinction instead.
 *
 * It lives here rather than inside the Intake page because the shell has to read
 * it too — the program bar names the curriculum being worked on, and while a new
 * one is being typed that is not the id in storage. A page-local `useState`
 * could not reach it: StageLayout renders the bar *above* the `Outlet`.
 */
export interface IntakeRouteState {
  creating?: boolean
}

/** Pass as the router's `state` to open intake on an empty form. */
export const CREATING_INTAKE = { creating: true } as const

/** Reading it back. `unknown` because `useLocation().state` is whatever the
 *  caller passed — including `null` on a plain navigation or a fresh load. */
export function isCreatingIntake(state: unknown): boolean {
  return (state as IntakeRouteState | null)?.creating === true
}
