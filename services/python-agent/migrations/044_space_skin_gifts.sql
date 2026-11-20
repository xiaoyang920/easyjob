ALTER TABLE user_space_skin
    DROP CHECK user_space_skin_chk_1,
    ADD CONSTRAINT user_space_skin_chk_1 CHECK (paid_coins >= 0);
