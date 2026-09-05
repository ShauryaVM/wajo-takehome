export type AutonomyLevel =
  | "proceed_silently"
  | "proceed_and_notify"
  | "ask_first"
  | "escalate";

export type Decision = {
  id: number;
  email_id: number;
  autonomy_level: AutonomyLevel;
  classifier_level: string;
  confidence: number;
  reasoning: string;
  proposed_action: Record<string, unknown>;
  action_type: string;
  status: string;
  safety_hit: string | null;
  executed_at: string | null;
  created_at: string;
};

export type EmailListItem = {
  id: number;
  subject: string;
  sender: string;
  preview: string;
  received_at: string;
  labels: string[];
  decision: Decision | null;
};

export type EmailDetail = EmailListItem & {
  body_text: string;
  to_addresses: string[];
  account_id: number;
  provider_message_id: string;
  feedback?: { id: number; feedback_type: string; user_comment: string | null; created_at: string }[];
};

export type FeedItem = {
  decision: Decision;
  email: {
    id: number;
    subject: string;
    sender: string;
    preview: string;
    received_at: string;
  };
  feedback: { id: number; feedback_type: string; user_comment: string | null; created_at: string }[];
};

export type ApprovalItem = {
  decision: Decision;
  email: {
    id: number;
    subject: string;
    sender: string;
    preview: string;
    body_text: string;
    received_at: string;
  };
};
