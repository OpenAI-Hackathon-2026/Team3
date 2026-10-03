'use client';

import { fetchAuthSession } from 'aws-amplify/auth';

const apiUrl = process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, '');

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  if (!apiUrl) throw new Error('The AWS API is not configured in this environment.');
  const session = await fetchAuthSession().catch(() => null);
  const token = session?.tokens?.idToken?.toString();
  const response = await fetch(`${apiUrl}${path}`, {
    ...options,
    headers: {
      'content-type': 'application/json',
      ...(token ? { authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(payload.error || 'The request could not be completed.', response.status);
  return payload as T;
}
