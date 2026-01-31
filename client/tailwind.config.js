/** @type {import('tailwindcss').Config} */
export default {
    content: [
        "./index.html",
        "./src/**/*.{js,ts,jsx,tsx}",
    ],
    theme: {
        extend: {
            colors: {
                background: '#FAF9F7',
                'background-secondary': '#FFFFFF',
                primary: '#D97706',
                'text-primary': '#1F1F1F',
                'text-secondary': '#6B6B6B',
                border: '#E5E5E5',
                success: '#10B981',
                error: '#EF4444',
            },
            fontFamily: {
                sans: ['Söhne', 'Inter', '-apple-system', 'BlinkMacSystemFont', 'sans-serif'],
                mono: ['Söhne Mono', 'Fira Code', 'monospace'],
            },
        },
    },
    plugins: [],
}
