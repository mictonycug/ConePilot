import { Router } from 'express';
import {
    getSessions,
    createSession,
    getSessionById,
    addCone,
    deleteCone,
    updateConePosition,
    deleteSession,
    updateSession
} from '../controllers/sessionController';
import { authenticateToken } from '../middleware/auth';

const router = Router();

router.use(authenticateToken);

router.get('/', getSessions);
router.post('/', createSession);
router.get('/:id', getSessionById);
router.put('/:id', updateSession);
router.delete('/:id', deleteSession);

// Cone management within session
router.post('/:id/cones', addCone);
router.delete('/:id/cones/:coneId', deleteCone);
router.put('/:id/cones/:coneId', updateConePosition);

export default router;
