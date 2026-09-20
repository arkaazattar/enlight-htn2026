export type Person = {
  id: string;
  name: string | null;
  label: string;
  facts: string[];
  context: Record<string, unknown>;
  image_paths: string[];
  note_paths: string[];
  image_url: string;
};
