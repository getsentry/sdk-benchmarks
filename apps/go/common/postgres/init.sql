-- World table: 10,000 rows, id 1-10000, randomNumber 1-10000
CREATE TABLE world (
    id integer NOT NULL,
    randomnumber integer NOT NULL DEFAULT 0,
    PRIMARY KEY (id)
);

-- Fortune table: 12 rows of fortune messages
CREATE TABLE fortune (
    id integer NOT NULL,
    message varchar(2048) NOT NULL DEFAULT '',
    PRIMARY KEY (id)
);

-- Seed World table with 10,000 rows
INSERT INTO world (id, randomnumber)
SELECT x.id, floor(random() * 10000 + 1)::integer
FROM generate_series(1, 10000) AS x(id);

-- Seed Fortune table (standard TechEmpower fortunes)
INSERT INTO fortune (id, message) VALUES
(1, 'fortune: No such file or directory'),
(2, 'A computer scientist is someone who fixes things that aren''t broken.'),
(3, 'After enough decimal places, nobody gives a damn.'),
(4, 'A bad random number generator: 1, 1, 1, 1, 1, 4.33e+67, 1, 1, 1'),
(5, 'A computer program does what you tell it to do, not what you want it to do.'),
(6, 'Emacs is a nice operating system, but I prefer UNIX. — Tom Strstrst.'),
(7, 'Any program that runs right is obsolete.'),
(8, 'A list is only as strong as its weakest link. — Donald Knuth'),
(9, 'Feature: A bug with seniority.'),
(10, 'Computers make very fast, very accurate mistakes.'),
(11, '&lt;script&gt;alert(&quot;This should not be displayed in a browser alert box.&quot;);&lt;/script&gt;'),
(12, 'フレームワークのベンチマーク');
