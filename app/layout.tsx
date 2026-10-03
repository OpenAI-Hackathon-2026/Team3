import type { Metadata } from 'next';
import './globals.css';
import { AuthProvider } from './auth-context';

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL || 'http://localhost:3000'),
  title: 'Second Serving — Good food, still in time',
  description: 'Reserve surplus meals and ingredients from kitchens near you.',
  openGraph: {
    title: 'Second Serving',
    description: 'Good food, still in time.',
    images: [{ url: '/og.png', width: 1677, height: 943, alt: 'Second Serving — Good food, still in time.' }],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Second Serving',
    description: 'Good food, still in time.',
    images: ['/og.png'],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
