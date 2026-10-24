import { GetObjectCommand, PutObjectCommand, S3Client } from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";
import { readFile } from "node:fs/promises";

const PRESIGN_SECONDS = 3600;

export type S3Config = { endpoint: string; accessKey: string; secretKey: string; bucket: string };

/** Returns null unless every S3_* variable is set, so local runs work without MinIO. */
export function s3ConfigFromEnv(env: NodeJS.ProcessEnv = process.env): S3Config | null {
  const { S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY, S3_BUCKET } = env;
  if (!S3_ENDPOINT || !S3_ACCESS_KEY || !S3_SECRET_KEY || !S3_BUCKET) return null;
  return { endpoint: S3_ENDPOINT, accessKey: S3_ACCESS_KEY, secretKey: S3_SECRET_KEY, bucket: S3_BUCKET };
}

/** Uploads a local file and returns a presigned GET url. */
export async function uploadVideo(cfg: S3Config, file: string, key: string): Promise<string> {
  const client = new S3Client({
    endpoint: cfg.endpoint,
    region: "us-east-1",
    forcePathStyle: true, // MinIO
    credentials: { accessKeyId: cfg.accessKey, secretAccessKey: cfg.secretKey },
  });
  await client.send(
    new PutObjectCommand({ Bucket: cfg.bucket, Key: key, Body: await readFile(file), ContentType: "video/mp4" }),
  );
  return getSignedUrl(client, new GetObjectCommand({ Bucket: cfg.bucket, Key: key }), {
    expiresIn: PRESIGN_SECONDS,
  });
}
