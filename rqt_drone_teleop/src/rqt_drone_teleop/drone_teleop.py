#!/usr/bin/env python

import os
import rospy
import rospkg

from qt_gui.plugin import Plugin
from python_qt_binding import loadUi
from python_qt_binding.QtWidgets import QWidget
from python_qt_binding.QtGui import QIcon, QPixmap, QImage
from python_qt_binding.QtCore import pyqtSignal, Qt

from sensor_msgs.msg import Image
import cv2
from cv_bridge import CvBridge
from std_msgs.msg import Bool, Float64
from geometry_msgs.msg import Pose, PoseStamped, Twist, TwistStamped

from teleopWidget import TeleopWidget
from sensorsWidget import SensorsWidget


class DroneTeleop(Plugin):
	def __init__(self, context):
		super(DroneTeleop, self).__init__(context)
		# Give QObjects reasonable names
		self.setObjectName('DroneTeleop')

		# Process standalone plugin command-line arguments
		from argparse import ArgumentParser
		parser = ArgumentParser()
		# Add argument(s) to the parser.
		parser.add_argument("-q", "--quiet", action="store_true",
                      dest="quiet",
                      help="Put plugin in silent mode")
		# args, unknowns = parser.parse_known_args(context.argv())
		# if not args.quiet:
		# 	print 'arguments: ', args
		# 	print 'unknowns: ', unknowns

		# Create QWidget
		self._widget = QWidget()
		# Get path to UI file which should be in the "resource" folder of this package
		ui_file = os.path.join(rospkg.RosPack().get_path(
			'rqt_drone_teleop'), 'resource', 'DroneTeleop_info.ui')
		# Extend the widget with all attributes and children from UI file
		loadUi(ui_file, self._widget)
		# Give QObjects reasonable names
		self._widget.setObjectName('DroneTeleopUi')
		# Show _widget.windowTitle on left-top of each plugin (when
		# it's set in _widget). This is useful when you open multiple
		# plugins at once. Also if you open multiple instances of your
		# plugin at once, these lines add number to make it easy to
		# tell from pane to pane.
		if context.serial_number() > 1:
			self._widget.setWindowTitle(
				self._widget.windowTitle() + (' (%d)' % context.serial_number()))

		# Add logo
		pixmap = QPixmap(os.path.join(rospkg.RosPack().get_path(
			'rqt_drone_teleop'), 'resource', 'jderobot.png'))
		self._widget.img_logo.setPixmap(pixmap.scaled(121, 121))

		# Set Variables
		self.play_code_flag = False
		self.takeoff = False
		self.linear_velocity_scaling_factor = 1
		self.vertical_velocity_scaling_factor = 0.8
		self.angular_velocity_scaling_factor = 0.5
		self._widget.term_out.setReadOnly(True)
		self._widget.term_out.setLineWrapMode(self._widget.term_out.NoWrap)

		# Set functions for each GUI Item
		self._widget.takeoffButton.clicked.connect(self.call_takeoff_land)
		self._widget.playButton.clicked.connect(self.call_play)
		self._widget.stopButton.clicked.connect(self.stop_drone)

		# Add Publishers
		self.takeoff_pub = rospy.Publisher('gui/takeoff_land', Bool, queue_size=1)
		self.play_stop_pub = rospy.Publisher('gui/play_stop', Bool, queue_size=1)
		self.twist_pub = rospy.Publisher('gui/twist', Twist, queue_size=1)

		#Add global variables
		self.shared_twist_msg = Twist()
		self.current_pose = Pose()
		self.current_twist = Twist()
		self.stop_icon = QIcon()
		self.stop_icon.addPixmap(QPixmap(os.path.join(rospkg.RosPack().get_path(
			'rqt_drone_teleop'), 'resource', 'stop.png')), QIcon.Normal, QIcon.Off)

		self.play_icon = QIcon()
		self.play_icon.addPixmap(QPixmap(os.path.join(rospkg.RosPack().get_path(
			'rqt_drone_teleop'), 'resource', 'play.png')), QIcon.Normal, QIcon.Off)

		self.bridge = CvBridge()

		self.teleop_stick_1 = TeleopWidget(self, 'set_linear_xy', 151)
		self._widget.tlLayout.addWidget(self.teleop_stick_1)
		self.teleop_stick_1.setVisible(True)

		self.teleop_stick_2 = TeleopWidget(self, 'set_alt_yawrate', 151)
		self._widget.tlLayout_2.addWidget(self.teleop_stick_2)
		self.teleop_stick_2.setVisible(True)

		self.sensors_widget = SensorsWidget(self)
		self._widget.sensorsCheck.stateChanged.connect(self.show_sensors_widget)

		# Add widget to the user interface
		context.add_widget(self._widget)

		# Add Subscibers
		cam_frontal_topic = rospy.get_param('cam_frontal_topic', '/iris/cam_frontal/image_raw')
		cam_ventral_topic = rospy.get_param('cam_ventral_topic', '/iris/cam_ventral/image_raw')
		rospy.Subscriber(cam_frontal_topic, Image, self.cam_frontal_cb)
		rospy.Subscriber(cam_ventral_topic, Image, self.cam_ventral_cb)
		rospy.Subscriber('interface/filtered_img', Image, self.filtered_img_cb)
		rospy.Subscriber('interface/threshed_img', Image, self.threshed_img_cb)
		rospy.Subscriber('mavros/local_position/pose',
		                 PoseStamped, self.pose_stamped_cb)
		rospy.Subscriber('mavros/local_position/velocity_body',
		                 TwistStamped, self.twist_stamped_cb)

	def show_sensors_widget(self, state):
		if state == Qt.Checked:
			self.sensors_widget.show()
		else:
			self.sensors_widget.hide()

	def msg_to_pixmap(self, msg):
		cv_img = self.bridge.imgmsg_to_cv2(msg)
		h, w, _ = cv_img.shape
		bytesPerLine = 3 * w
		q_img = QImage(cv_img.data, w, h, bytesPerLine, QImage.Format_RGB888)
		return QPixmap.fromImage(q_img).scaled(320, 240)

	def cam_frontal_cb(self, msg):
		self._widget.img_frontal.setPixmap(self.msg_to_pixmap(msg))
		self.sensors_widget.sensorsUpdate.emit()

	def cam_ventral_cb(self, msg):
		self._widget.img_ventral.setPixmap(self.msg_to_pixmap(msg))

	def threshed_img_cb(self, msg):
		self._widget.img_threshed.setPixmap(self.msg_to_pixmap(msg))

	def filtered_img_cb(self, msg):
		self._widget.img_filtered.setPixmap(self.msg_to_pixmap(msg))

	def pose_stamped_cb(self, msg):
		self.current_pose = msg.pose
		self.set_info_pos(self.current_pose)

	def twist_stamped_cb(self, msg):
		self.current_twist = msg.twist
		self.set_info_vel(self.current_twist)

	def set_info_pos(self, pose):
		self._widget.posX.setText(str(round(pose.position.x, 1)))
		self._widget.posY.setText(str(round(pose.position.y, 1)))
		self._widget.posZ.setText(str(round(pose.position.z, 1)))

	def set_info_vel(self, twist):
		self._widget.velX.setText(str(round(twist.linear.x, 1)))
		self._widget.velY.setText(str(round(twist.linear.y, 1)))
		self._widget.velZ.setText(str(round(twist.linear.z, 1)))

	def call_takeoff_land(self):
		if self.takeoff == True:
			self._widget.takeoffButton.setText("Take Off")
			rospy.loginfo('Landing')
			self._widget.term_out.append('Landing')
			self.takeoff_pub.publish(Bool(False))
			self.takeoff = False
		else:
			self._widget.takeoffButton.setText("Land")
			rospy.loginfo('Taking off')
			self._widget.term_out.append('Taking off')
			self.takeoff_pub.publish(Bool(True))
			self.takeoff = True

	def call_play(self):
		if not self.play_code_flag:
			self._widget.playButton.setText('Stop Code')
			self._widget.playButton.setStyleSheet("background-color: #ec7063")
			self._widget.playButton.setIcon(self.stop_icon)
			rospy.loginfo('Executing student code')
			self._widget.term_out.append('Executing student code')
			self.play_stop_pub.publish(Bool(True))
			self.play_code_flag = True
		else:
			self._widget.playButton.setText('Play Code')
			self._widget.playButton.setStyleSheet("background-color: #7dcea0")
			self._widget.playButton.setIcon(self.play_icon)
			rospy.loginfo('Stopping student code')
			self._widget.term_out.append('Stopping student code')
			self.play_stop_pub.publish(Bool(False))
			self.play_code_flag = False
		
	def stop_drone(self):
		self._widget.term_out.append('Stopping Drone')
		rospy.loginfo('Stopping Drone')
		self.teleop_stick_1.stop()
		self.teleop_stick_2.stop()
		if self.play_code_flag:
			self.call_play()
		for i in range(5):
			self.shared_twist_msg = Twist()
			self.twist_pub.publish(self.shared_twist_msg)
			rospy.sleep(0.05)

	def set_linear_xy(self, u, v):
		x = -self.linear_velocity_scaling_factor * v
		y = -self.linear_velocity_scaling_factor * u
		self._widget.XValue.setText('%.2f' % x)
		self._widget.YValue.setText('%.2f' % y)
		rospy.logdebug('Stick 2 value changed to - x: %.2f y: %.2f', x, y)
		self.shared_twist_msg.linear.x = x
		self.shared_twist_msg.linear.y = y
		self.twist_pub.publish(self.shared_twist_msg)

	def set_alt_yawrate(self, u, v):
		az = -self.vertical_velocity_scaling_factor * u
		z = -self.angular_velocity_scaling_factor * v
		self._widget.rotValue.setText('%.2f' % az)
		self._widget.altdValue.setText('%.2f' % z)
		rospy.logdebug('Stick 1 value changed to - az: %.2f z: %.2f', az, z)
		self.shared_twist_msg.linear.z = z
		self.shared_twist_msg.angular.z = az
		self.twist_pub.publish(self.shared_twist_msg)

	def shutdown_plugin(self):
		# TODO unregister all publishers here
		pass

	def save_settings(self, plugin_settings, instance_settings):
		# TODO save intrinsic configuration, usually using:
		# instance_settings.set_value(k, v)
		pass

	def restore_settings(self, plugin_settings, instance_settings):
		# TODO restore intrinsic configuration, usually using:
		# v = instance_settings.value(k)
		pass

	#def trigger_configuration(self):
	# Comment in to signal that the plugin has a way to configure
	# This will enable a setting button (gear icon) in each dock widget title bar
	# Usually used to open a modal configuration dialog
