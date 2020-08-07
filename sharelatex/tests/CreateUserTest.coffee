module.exports = (grunt) ->

	grunt.registerTask 'user:test', "Create a test user with the given email address. Usage: grunt user:test --email=joe@example.com", () ->
		done = @async()
		email = grunt.option("email")
		if !email?
			console.error "Usage: grunt user:test --email=joe@example.com"
			process.exit(1)

		settings = require "settings-sharelatex"
		UserRegistrationHandler = require "../web/app/src/Features/User/UserRegistrationHandler"
		OneTimeTokenHandler = require "../web/app/src/Features/Security/OneTimeTokenHandler"
		UserRegistrationHandler.registerNewUser {
			email: email
			# NOTE(msimonin): we need a /strong/ password otherwise we don't validate
			password: "Testtest42"
		}, (error, user) ->
			if error? and error?.message != "EmailAlreadyRegistered"
				throw error
			user.isAdmin = false
			user.confirmed = true
			user.save (error) ->
				throw error if error?
				ONE_WEEK = 7 * 24 * 60 * 60 # seconds
				OneTimeTokenHandler.getNewToken "password", { expiresIn: ONE_WEEK, email:user.email, user_id: user._id.toString() }, (err, token)->
					return next(err) if err?

					console.log ""
					console.log """
						Successfully created and validated #{email} as an regular user.
					"""
					done()

