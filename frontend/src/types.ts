export type Course = {
  id: string; code: string; subject: string; name: string; credits: number;
  offered: string; description: string; prereq_text?: string; departments: string[];
};
export type Program = { id: string; name: string; degree: string; description: string };
/** courseId -> list of OR-groups (all groups required) */
export type Prereqs = Record<string, string[][]>;

/** transfers: courseId -> school, for credits imported from a DegreeWorks audit that were earned elsewhere */
export type Term = { name: string; kind: 'Fall' | 'Spring' | 'Summer' | 'Winter'; courses: string[]; transfers?: Record<string, string>; extra?: number; imported?: boolean };   // extra: credits from audit rows not in our catalog; imported: from a DegreeWorks audit (prereqs not checked)
/** A real CUNYfirst class section. `start`/`end` are minutes past midnight; null for async/TBA. */
export type Section = {
  sec: string; component: string; days: string; start: number | null; end: number | null;
  extra: { days: string; start: number; end: number }[];
  room: string; instr: string; mode: string; status: string; raw: string;
};
/** The student's weekly availability. Days are the 2-char CUNYfirst tokens: Mo Tu We Th Fr Sa Su. */
export type Availability = { busy: [string, number, number][]; earliest: number; latest: number };
/** verified=false: a 200+ course with no prerequisite found in any source — confirm with an advisor
 *  sections=null: we have no schedule data for this course, which is NOT the same as "nothing fits" */
export type Suggestion = {
  id: string; reason: string; unlocks: string[]; verified: boolean; source: string | null;
  sections: Section[] | null;
};
export type Violation = { id: string; term: number; missing: string[] };
export type AuditRequirement = { title: string; parent: string | null; courses: string[]; page: number | null };
export type Progress = {
  credits: number;
  major: {
    name: string; have: number; need: number; unit: string; set: string | null;
    completed?: string[][]; missing: string[][]; auditCompleted?: AuditRequirement[];
  }[];
  pathways: { slot: string; label: string; course: string | null }[];
};
export type SuggestResponse = {
  suggested: Suggestion[]; candidates: Suggestion[]; progress: Progress; source: 'gemini' | 'heuristic'; violations: Violation[];
  /** basis='published': the registrar has released this term's schedule. 'pattern': same season, a year on —
   *  a fair guide to when a course usually meets, but not a booking. null: no section data scraped. */
  schedule: { basis: 'published' | 'pattern'; scraped: string } | null;
};
export type AuditImport = {
  program: string | null;
  major: string | null;
  degree: string | null;
  terms: Term[];
  courses: { id: string; code: string; grade: string; credits: number; term: Term['kind']; year: number; transfer: string | null }[];
  completedRequirements: AuditRequirement[];
  error?: string;
};
