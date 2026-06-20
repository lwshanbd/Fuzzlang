enum State { IDLE, RUN, STOP };
int next(enum State s) {
    switch (s) {
    case IDLE: return RUN;
    case RUN: return STOP;
    case STOP: return IDLE;
    }
    return IDLE;
}
int main(void) {
    return next(RUN);
}
