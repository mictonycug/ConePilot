
import { PrismaClient } from '@prisma/client';
import bcrypt from 'bcryptjs';
import dotenv from 'dotenv';

// Load .env
dotenv.config();

const prisma = new PrismaClient();

async function main() {
    const email = 'admin@conepilot.com';
    const password = 'password123';
    const name = 'Admin User';

    // Check if user exists
    const existingUser = await prisma.user.findUnique({
        where: { email },
    });

    if (existingUser) {
        console.log(`User ${email} already exists.`);
        return;
    }

    // Hash password
    const hashedPassword = await bcrypt.hash(password, 10);

    // Create user
    const user = await prisma.user.create({
        data: {
            email,
            password: hashedPassword,
            name,
        },
    });

    console.log(`User created: ${user.email}`);
    console.log(`Password: ${password}`);
}

main()
    .catch((e) => {
        console.error(e);
        process.exit(1);
    })
    .finally(async () => {
        await prisma.$disconnect();
    });
