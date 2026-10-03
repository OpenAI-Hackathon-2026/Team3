'use client';

import { Amplify } from 'aws-amplify';

let configured = false;

export function configureAmplify() {
  if (configured) return;
  const userPoolId = process.env.NEXT_PUBLIC_COGNITO_USER_POOL_ID;
  const userPoolClientId = process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID;
  if (!userPoolId || !userPoolClientId) return;
  Amplify.configure({
    Auth: {
      Cognito: {
        userPoolId,
        userPoolClientId,
        loginWith: { email: true },
        signUpVerificationMethod: 'code',
      },
    },
  });
  configured = true;
}

export function isAwsConfigured() {
  return Boolean(
    process.env.NEXT_PUBLIC_COGNITO_USER_POOL_ID &&
    process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID &&
    process.env.NEXT_PUBLIC_API_URL,
  );
}
