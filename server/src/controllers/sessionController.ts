import { Request, Response } from 'express';
import prisma from '../services/db';
import { SessionStatus, ConeStatus } from '@prisma/client';

export const getSessions = async (req: Request, res: Response) => {
    try {
        const userId = req.user?.id;
        if (!userId) return res.status(401).json({ message: 'Unauthorized' });

        const sessions = await prisma.session.findMany({
            where: { userId },
            orderBy: { updatedAt: 'desc' },
            include: {
                cones: true
            }
        });

        res.json({ sessions });
    } catch (error) {
        console.error('GetSessions error:', error);
        res.status(500).json({ message: 'Internal server error' });
    }
};

export const createSession = async (req: Request, res: Response) => {
    try {
        const userId = req.user?.id;
        if (!userId) return res.status(401).json({ message: 'Unauthorized' });

        const { name, fieldWidth, fieldHeight } = req.body;

        const session = await prisma.session.create({
            data: {
                userId,
                name: name || 'Untitled Session',
                fieldWidth: fieldWidth || 3.0,
                fieldHeight: fieldHeight || 3.0,
                status: SessionStatus.SETUP,
            },
        });

        res.status(201).json({ session });
    } catch (error) {
        console.error('CreateSession error:', error);
        res.status(500).json({ message: 'Internal server error' });
    }
};

export const getSessionById = async (req: Request, res: Response) => {
    try {
        const userId = req.user?.id;
        const { id } = req.params;

        if (!userId) return res.status(401).json({ message: 'Unauthorized' });

        const session = await prisma.session.findUnique({
            where: { id },
            include: {
                cones: {
                    orderBy: { orderIndex: 'asc' }
                },
                robotPath: true
            }
        });

        if (!session) return res.status(404).json({ message: 'Session not found' });
        if (session.userId !== userId) return res.status(403).json({ message: 'Forbidden' });

        res.json({ session });
    } catch (error) {
        console.error('GetSessionById error:', error);
        res.status(500).json({ message: 'Internal server error' });
    }
};

export const addCone = async (req: Request, res: Response) => {
    try {
        const userId = req.user?.id;
        const { id } = req.params; // session id
        const { x, y } = req.body;

        // Verify ownership
        const session = await prisma.session.findUnique({ where: { id } });
        if (!session || session.userId !== userId) return res.status(403).json({ message: 'Forbidden' });

        const cone = await prisma.cone.create({
            data: {
                sessionId: id,
                x,
                y,
                status: ConeStatus.PENDING
            }
        });

        res.status(201).json({ cone });
    } catch (error) {
        console.error('AddCone error:', error);
        res.status(500).json({ message: 'Internal server error' });
    }
};

export const deleteCone = async (req: Request, res: Response) => {
    try {
        const userId = req.user?.id;
        const { coneId } = req.params;

        const cone = await prisma.cone.findUnique({
            where: { id: coneId },
            include: { session: true }
        });

        if (!cone || cone.session.userId !== userId) return res.status(403).json({ message: 'Forbidden' });

        await prisma.cone.delete({ where: { id: coneId } });

        res.json({ success: true });
    } catch (error) {
        console.error('DeleteCone error:', error);
        res.status(500).json({ message: 'Internal server error' });
    }
};

export const updateConePosition = async (req: Request, res: Response) => {
    try {
        const userId = req.user?.id;
        const { coneId } = req.params;
        const { x, y } = req.body;

        const cone = await prisma.cone.findUnique({
            where: { id: coneId },
            include: { session: true }
        });

        if (!cone || cone.session.userId !== userId) return res.status(403).json({ message: 'Forbidden' });

        const updatedCone = await prisma.cone.update({
            where: { id: coneId },
            data: { x, y }
        });

        res.json({ cone: updatedCone });
    } catch (error) {
        console.error('UpdateCone error:', error);
        res.status(500).json({ message: 'Internal server error' });
    }
};

export const deleteSession = async (req: Request, res: Response) => {
    try {
        const userId = req.user?.id;
        const { id } = req.params;

        if (!userId) return res.status(401).json({ message: 'Unauthorized' });

        const session = await prisma.session.findUnique({
            where: { id }
        });

        if (!session) return res.status(404).json({ message: 'Session not found' });
        if (session.userId !== userId) return res.status(403).json({ message: 'Forbidden' });

        await prisma.session.delete({ where: { id } });

        res.json({ success: true, message: 'Session deleted' });
    } catch (error) {
        console.error('DeleteSession error:', error);
        res.status(500).json({ message: 'Internal server error' });
    }
};

export const updateSession = async (req: Request, res: Response) => {
    try {
        const userId = req.user?.id;
        const { id } = req.params;
        const { name } = req.body;

        if (!userId) return res.status(401).json({ message: 'Unauthorized' });

        const session = await prisma.session.findUnique({
            where: { id }
        });

        if (!session) return res.status(404).json({ message: 'Session not found' });
        if (session.userId !== userId) return res.status(403).json({ message: 'Forbidden' });

        const updatedSession = await prisma.session.update({
            where: { id },
            data: { name }
        });

        res.json({ session: updatedSession });
    } catch (error) {
        console.error('UpdateSession error:', error);
        res.status(500).json({ message: 'Internal server error' });
    }
};
