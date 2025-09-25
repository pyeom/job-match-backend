-- Database initialization script for job-match application
-- This script ensures the pgvector extension is available

-- Create the pgvector extension if it doesn't already exist
-- The pgvector/pgvector Docker image should have this extension available
CREATE EXTENSION IF NOT EXISTS vector;

-- Verify the extension is loaded
SELECT extension_name, extension_version
FROM pg_extension
WHERE extension_name = 'vector';

-- Optional: Create a test to ensure vector operations work
-- This will be removed by migrations but serves as a verification
DO $$
BEGIN
    -- Test basic vector functionality
    PERFORM '[1,2,3]'::vector;
    RAISE NOTICE 'pgvector extension is working correctly';
EXCEPTION
    WHEN OTHERS THEN
        RAISE EXCEPTION 'pgvector extension not working: %', SQLERRM;
END
$$;