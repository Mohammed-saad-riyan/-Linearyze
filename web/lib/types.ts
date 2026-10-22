// Mirrors api/app/assistant/pipeline.py and api/app/advisor/pipeline.py.

export type Lang = "en" | "ar";
export type Role = "management" | "employee" | "admin";

export interface Me {
  email: string;
  name: string;
  role: Role;
  events: string[];
  capabilities: string[];
}

export interface SourceRef {
  page?: number;
  heading?: string;
  sheet?: string;
  cell_range?: string;
}

export interface Citation {
  document_id: string;
  chunk_id: number;
  quote: string;
  start: number;
  end: number;
  source: SourceRef;
}

export interface DocumentCard {
  id: string;
  title: string;
  title_alt?: string;
  doc_type: string;
  language: Lang;
  reference?: string;
  date?: string;
  date_kind?: "received" | "submitted" | "dated";
  sender?: string;
  recipient?: string;
  version: number;
  is_latest: boolean;
  file_name: string;
  mime_type: string;
  view_chunk_id?: number;
}

export interface Sentence {
  text: string;
  citations: Citation[];
}

export interface ConflictValue {
  document_id: string;
  value: string;
  citation: Citation;
}

export interface MessageResponse {
  output: "E";
  lang: Lang;
  message_id: string;
  message: string;
  debug?: never; // M1 bodies are built from the constant alone, debug included (SRS 1.5.4)
}

export interface AssistantAnswer {
  output: "A" | "B" | "C" | "D";
  lang: Lang;
  notice?: string;
  sentences?: Sentence[];
  conflicts?: { fact_key: string; values: ConflictValue[] }[];
  documents?: DocumentCard[];
  question?: string;
  options?: string[];
  disclaimer?: string;
  debug?: Record<string, unknown>;
}

export type AssistantResponse = AssistantAnswer | MessageResponse;

export interface AdvisorInput {
  term: string;
  value: string;
  unit: string;
  source_type: "document" | "query" | "conversation";
  document_id?: string;
  document_title?: string;
  citation?: Citation;
  overridden_value?: string;
  overridden_document_title?: string;
  overridden_citation?: Citation;
}

export interface AdvisorAnswer {
  output: "R" | "Q";
  lang: Lang;
  notice?: string;
  result?: { value: string; unit: string; exact: string; rounded_up: boolean };
  formula?: string;
  formula_source?: "user" | "ai_selected";
  substituted?: string;
  inputs?: AdvisorInput[];
  notes?: string[];
  estimate?: boolean;
  question?: string;
  missing?: string[];
  choices?: { value: string; document_title: string; citation: Citation }[];
  documents?: DocumentCard[];
  disclaimer?: string;
  debug?: Record<string, unknown>;
}

export type AdvisorResponse = AdvisorAnswer | MessageResponse;

// What the client measured about a response. Shown in the debug strip so the four M1
// causes can be compared byte for byte and by time.
export interface Receipt {
  status: number;
  bytes: number;
  sha256: string;
  ms: number;
}

export interface PassageView {
  document_id: string;
  title: string;
  file_name: string;
  language: Lang;
  chunk_id: number;
  passages: {
    id: number;
    text_original: string;
    page?: number;
    heading?: string;
    sheet?: string;
    cell_range?: string;
  }[];
}
