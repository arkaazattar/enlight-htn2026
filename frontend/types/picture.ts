export type Picture = {
  id: string;
  objectKey: string;
  capturedAt?: string | null;
  createdAt?: string;
};

const devTime = async () => { return "&nbsp;"; }