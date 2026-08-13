// Пул подключений и миграции. ORM нет намеренно: запросов немного,
// а явный SQL читается лучше, чем цепочка методов.

import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import pg from 'pg';
import {config} from './config.js';

const here = path.dirname(fileURLToPath(import.meta.url));

export const pool = new pg.Pool({
	connectionString: config.databaseUrl,
	// Railway отдаёт Postgres с самоподписанным сертификатом.
	ssl: config.databaseUrl.includes('localhost') ? false : {rejectUnauthorized: false},
	max: 10,
});

export const q = (text, params) => pool.query(text, params);

export const one = async (text, params) => {
	const {rows} = await pool.query(text, params);
	return rows[0] ?? null;
};

export const many = async (text, params) => {
	const {rows} = await pool.query(text, params);
	return rows;
};

// Транзакция с автоматическим откатом при ошибке.
export const tx = async (fn) => {
	const client = await pool.connect();
	try {
		await client.query('BEGIN');
		const out = await fn(client);
		await client.query('COMMIT');
		return out;
	} catch (err) {
		await client.query('ROLLBACK');
		throw err;
	} finally {
		client.release();
	}
};

export const migrate = async () => {
	await q(`CREATE TABLE IF NOT EXISTS _migrations (
		name TEXT PRIMARY KEY,
		applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
	)`);

	const dir = path.join(here, '..', 'migrations');
	const files = fs.readdirSync(dir).filter((f) => f.endsWith('.sql')).sort();

	for (const file of files) {
		const done = await one('SELECT name FROM _migrations WHERE name = $1', [file]);
		if (done) continue;

		const sql = fs.readFileSync(path.join(dir, file), 'utf8');
		await tx(async (client) => {
			await client.query(sql);
			await client.query('INSERT INTO _migrations(name) VALUES ($1)', [file]);
		});
		console.log(`  миграция ${file} применена`);
	}
};
