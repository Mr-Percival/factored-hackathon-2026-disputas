// Único lugar donde se nombran los tipos de la API. Salen del esquema OpenAPI que genera FastAPI
// (`python scripts/export_openapi.py` + `npm run gen:api`): si el backend cambia un contrato, `npm run
// typecheck` falla aquí y no en producción.
import type { components } from "./schema";

type Schemas = components["schemas"];

export type ScenariosResponse = Schemas["ScenariosResponse"];
export type Scenario = Schemas["Scenario"];
export type ScriptTurn = Schemas["ScriptTurn"];
export type QuickReply = Schemas["QuickReply"];
export type SessionInfo = Schemas["SessionInfo"];
export type ConversationCreated = Schemas["ConversationCreated"];
export type TurnResult = Schemas["TurnResult"];
export type Outcome = TurnResult["outcome"];
export type TraceStep = Schemas["TraceStep"];
export type ToolCall = Schemas["ToolCall"];
export type Decision = Schemas["Decision"];
export type Rule = Schemas["Rule"];
export type Handoff = Schemas["Handoff"];
export type Candidate = Schemas["Candidate"];
export type ErrorBody = Schemas["ErrorBody"];
export type Category = Scenario["category"];
